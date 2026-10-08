"""Reviewed roster changes lock rounds before teams and revoke superseded access."""

import csv
import hashlib
import hmac
import io
import re

from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.db import connection, transaction

from .api import ApiProblem
from .clock import database_now
from .models import AuditEvent, Incident, RosterProposal, Round, Team, TeamSession
from .results import audit_replay, digest, record_action, validate_request
from .rules import require_staff_permission

FIELDS = ["code", "name", "leader_name", "member_count", "roster_reference", "status"]


def locked_roster(is_demo):
    with connection.cursor() as cursor:
        cursor.execute("SELECT pg_advisory_xact_lock(%s, %s)", [1069, int(is_demo)])
    rounds = list(Round.objects.select_for_update().filter(is_demo=is_demo).order_by("pk"))
    teams = list(Team.objects.select_for_update().filter(is_demo=is_demo).order_by("pk"))
    return rounds, teams


def roster_digest(rounds, teams):
    return digest(
        {
            "rounds": [
                {"id": item.pk, "state": item.state, "version": item.control_version}
                for item in rounds
            ],
            "teams": [
                {
                    field: getattr(item, field)
                    for field in ["id", *FIELDS, "session_version", "roster_digest"]
                }
                for item in teams
            ],
        }
    )


def validate_rows(rows):
    if not isinstance(rows, list) or not 1 <= len(rows) <= 500:
        raise ApiProblem("invalid_roster", "Supply 1–500 roster records.")
    normalized, seen = [], set()
    for index, row in enumerate(rows, 1):
        if not isinstance(row, dict) or set(row) != set(FIELDS):
            raise ApiProblem("invalid_roster", f"Row {index} requires exactly: {','.join(FIELDS)}.")
        code = row["code"]
        if (
            not isinstance(code, str)
            or not re.fullmatch(r"[A-Z0-9][A-Z0-9_-]{0,23}", code)
            or code in seen
        ):
            raise ApiProblem(
                "invalid_roster", f"Row {index} has an invalid or duplicate team code."
            )
        seen.add(code)
        for field, limit in [("name", 100), ("leader_name", 100), ("roster_reference", 200)]:
            if not isinstance(row[field], str) or not row[field].strip() or len(row[field]) > limit:
                raise ApiProblem(
                    "invalid_roster", f"Row {index} requires {field} of at most {limit} characters."
                )
        count = row["member_count"]
        if (
            type(count) is bool
            or str(count) not in ["3", "4"]
            or row["status"] not in Team.Status.values
        ):
            raise ApiProblem(
                "invalid_roster", f"Row {index} requires 3–4 members and a valid team status."
            )
        normalized.append({**row, "member_count": int(count)})
    return normalized


def validate_changes(rounds, teams, rows, is_demo):
    released = any(item.state != "DRAFT" for item in rounds)
    existing = {team.code: team for team in teams}
    for row in rows:
        team = existing.get(row["code"])
        other = Team.objects.filter(code=row["code"]).first()
        if other and other.is_demo != is_demo:
            raise ApiProblem(
                "invalid_roster", "Team codes cannot move between demo and real cohorts."
            )
        if not team:
            if released:
                raise ApiProblem(
                    "roster_locked", "Create the roster before any cohort round is released.", 409
                )
            if (
                row["status"] != "ACTIVE"
                or get_user_model().objects.filter(username=row["code"]).exists()
            ):
                raise ApiProblem(
                    "account_conflict", "New active teams require unused account names.", 409
                )
        else:
            if released and any(
                row[field] != getattr(team, field) for field in FIELDS if field != "status"
            ):
                raise ApiProblem(
                    "roster_locked",
                    "Roster identity is locked after release; status decisions remain reviewable.",
                    409,
                )
            if released and row["status"] == "ACTIVE" and team.status != "ACTIVE":
                raise ApiProblem(
                    "roster_locked", "Reactivation after release requires event adjudication.", 409
                )


@transaction.atomic
def propose_roster(actor, data):
    require_staff_permission(actor, "control_round")
    action_id, reason = validate_request(data)
    if type(data.get("is_demo")) is not bool:
        raise ApiProblem("invalid_roster", "Choose the demo or real cohort explicitly.")
    rounds, teams = locked_roster(data["is_demo"])
    fingerprint = {**data, "kind": "propose_roster", "actor_id": actor.pk}
    if replay := audit_replay(action_id, fingerprint):
        return replay
    rows = data.get("rows")
    if "csv" in data:
        content = data["csv"]
        if not isinstance(content, str) or len(content.encode()) > 1_000_000:
            raise ApiProblem("invalid_roster", "Roster CSV must be at most 1 MB.")
        try:
            reader = csv.DictReader(io.StringIO(content.lstrip("\ufeff")), strict=True)
            if reader.fieldnames != FIELDS:
                raise ApiProblem("invalid_roster", "Required columns: " + ",".join(FIELDS))
            rows = list(reader)
        except csv.Error:
            raise ApiProblem("invalid_roster", "Malformed roster CSV.") from None
    rows = validate_rows(rows)
    validate_changes(rounds, teams, rows, data["is_demo"])
    proposal = RosterProposal.objects.create(
        maker=actor,
        reason=reason,
        evidence_digest=roster_digest(rounds, teams),
        payload={"is_demo": data["is_demo"], "rows": rows},
    )
    response = {"proposal_id": proposal.pk, "rows": rows}
    record_action(action_id, actor, "propose_roster", reason, fingerprint, response)
    return response


@transaction.atomic
def review_roster(actor, data):
    require_staff_permission(actor, "verify_evidence")
    action_id, reason = validate_request(data)
    proposal = (
        RosterProposal.objects.select_related("maker").filter(pk=data.get("proposal_id")).first()
        if type(data.get("proposal_id")) is int
        else None
    )
    if not proposal:
        raise ApiProblem("not_found", "Roster proposal not found.", 404)
    rounds, teams = locked_roster(proposal.payload["is_demo"])
    fingerprint = {**data, "kind": "review_roster", "actor_id": actor.pk}
    if replay := audit_replay(action_id, fingerprint):
        return replay
    if proposal.maker_id == actor.pk:
        raise ApiProblem(
            "independent_reviewer", "A different verifier must review the roster.", 403
        )
    if AuditEvent.objects.filter(
        action="review_roster", after__response__proposal_id=proposal.pk
    ).exists():
        raise ApiProblem("already_reviewed", "This roster proposal has already been reviewed.", 409)
    require_staff_permission(proposal.maker, "control_round")
    reject = data.get("reject") is True
    if not reject:
        if proposal.evidence_digest != roster_digest(rounds, teams):
            raise ApiProblem(
                "stale_evidence", "Roster or round release changed; prepare a fresh proposal.", 409
            )
        if data.get("evidence_confirmed") is not True:
            raise ApiProblem(
                "evidence_required", "Confirm independent review of roster and status evidence."
            )
        rows = validate_rows(proposal.payload["rows"])
        validate_changes(rounds, teams, rows, proposal.payload["is_demo"])
        existing = {team.code: team for team in teams}
        now = database_now()
        changed = []
        for row in rows:
            team = existing.get(row["code"])
            if team and all(getattr(team, field) == value for field, value in row.items()):
                continue
            if not team:
                user = get_user_model().objects.create_user(username=row["code"])
                # Issue credentials separately through Django's password form.
                team = Team(user=user, is_demo=proposal.payload["is_demo"])
            else:
                team.session_version += 1
                TeamSession.objects.filter(team=team, revoked_at__isnull=True).update(
                    revoked_at=now
                )
            for field, value in row.items():
                setattr(team, field, value)
            team.roster_digest = digest(row)
            team.full_clean()
            team.save()
            changed.append(team.code)
        if changed:
            for round in rounds:
                round.control_version += 1
                round.save(update_fields=["control_version"])
                if round.state == "FINALIZED":
                    Incident.objects.create(
                        round=round,
                        category="QUALIFICATION_IMPACT",
                        material=True,
                        affected_scope={
                            "team_codes": changed,
                            "summary": "Reviewed roster status changed after final publication.",
                        },
                        opened_at=now,
                        owner=actor,
                        evidence_references=[f"roster-proposal:{proposal.pk}"],
                    )
    response = {"proposal_id": proposal.pk, "rejected": reject}
    record_action(action_id, actor, "review_roster", reason, fingerprint, response)
    return response


@transaction.atomic
def credentials(actor, team_id, data):
    require_staff_permission(actor, "control_round")
    action_id, reason = validate_request(data)
    team = Team.objects.select_for_update().select_related("user").filter(pk=team_id).first()
    if not team or team.status != "ACTIVE" or team.user.is_staff or team.user.is_superuser:
        raise ApiProblem("invalid_team", "Choose an active participant team.")
    password = data.get("password")
    if not isinstance(password, str) or not 8 <= len(password) <= 128:
        raise ApiProblem("invalid_password", "Supply a password of 8–128 characters.")
    fingerprint = {
        "kind": "team_credentials",
        "team_id": team_id,
        "actor_id": actor.pk,
        "expected_version": data.get("expected_version"),
        "reason": reason,
        "password_fingerprint": hmac.new(
            settings.SECRET_KEY.encode(), f"{action_id}:{password}".encode(), hashlib.sha256
        ).hexdigest(),
    }
    if replay := audit_replay(action_id, fingerprint):
        return replay
    if (
        type(data.get("expected_version")) is not int
        or data["expected_version"] != team.session_version
    ):
        raise ApiProblem(
            "stale_evidence", "Team access changed; refresh before issuing credentials.", 409
        )
    try:
        validate_password(password, team.user)
    except ValidationError as exc:
        raise ApiProblem("invalid_password", " ".join(exc.messages)) from None
    team.user.set_password(password)
    team.user.save(update_fields=["password"])
    team.session_version += 1
    team.save(update_fields=["session_version"])
    TeamSession.objects.filter(team=team, revoked_at__isnull=True).update(revoked_at=database_now())
    response = {
        "team_id": team.pk,
        "username": team.user.get_username(),
        "session_version": team.session_version,
    }
    record_action(action_id, actor, "team_credentials", reason, fingerprint, response)
    return response
