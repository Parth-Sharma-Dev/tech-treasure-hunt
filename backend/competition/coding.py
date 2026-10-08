"""Durable source saves and locked final bundles; submitted code is never executed."""

import hashlib
import uuid

from django.db import transaction
from django.views.decorators.debug import sensitive_variables

from .api import ApiProblem
from .clock import active_elapsed, clock_payload, database_now
from .coding_content import tasks_snapshot
from .gameplay import attempt_uuid, shared_round, write_team
from .models import CodingRevision, CodingSubmission, CodingWorkstation, Team, TeamSession
from .participant import round_eligible
from .results import audit_replay, digest, locked_round, record_action, validate_request
from .rules import require_staff_permission
from .sessions import require_team


def source_hash(body):
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


def native_round(round, team=None):
    if (
        round.number != 3
        or round.delivery_mode != "CODING"
        or (team and round.is_demo != team.is_demo)
    ):
        raise ApiProblem("not_found", "Native coding round not found.", 404)
    if round.state != "DRAFT" and tasks_snapshot(round) != round.rules_snapshot.get("coding_tasks"):
        raise ApiProblem(
            "evidence_gap", "The released task set needs organizer reconciliation.", 409
        )


def latest_revisions(round, team, cutoff=None):
    query = CodingRevision.objects.filter(round=round, team=team)
    if cutoff is not None:
        query = query.filter(admitted_at__lte=cutoff)
    latest = {}
    for item in query.order_by("task_id", "-revision"):
        latest.setdefault(item.task_id, item)
    return latest


def revision_payload(item):
    return {
        "id": item.pk,
        "task_id": item.task_id,
        "revision": item.revision,
        "language": item.language,
        "body": item.body,
        "source_hash": item.source_hash,
        "action_id": str(item.action_id),
        "saved_at": item.admitted_at.isoformat(),
    }


def submission_payload(item):
    return {
        "id": item.pk,
        "kind": item.kind,
        "submitted_at": item.submitted_at.isoformat(),
        "active_elapsed_ms": item.active_elapsed_ms,
        "manifest": item.manifest,
        "manifest_digest": item.manifest_digest,
    }


def assigned_session(request, round, team):
    station = CodingWorkstation.objects.filter(round=round, team=team).first()
    return station, bool(station and station.session_id == request.team_session.pk)


def live_permission(request, round, team, now):
    if not round_eligible(team, round):
        raise ApiProblem("ineligible", "Your team is not eligible for this coding round.", 403)
    if round.play_mode != "ONLINE" or round.state != "LIVE" or now > round.deadline_at:
        raise ApiProblem(
            "round_closed", "Coding saves are available only during live play before cutoff.", 409
        )
    if not assigned_session(request, round, team)[1]:
        raise ApiProblem(
            "workstation_required",
            "Ask the supervisor to assign this browser to your workstation.",
            403,
        )


@transaction.atomic
def workspace(request, round_id):
    team = require_team(request, allow_inactive=True, touch=False)
    round = shared_round(round_id)
    native_round(round, team)
    team = write_team(request)
    now = database_now()
    station, assigned = assigned_session(request, round, team)
    final = CodingSubmission.objects.filter(round=round, team=team).first()
    state = clock_payload(round, now)["state"]
    eligible = round_eligible(team, round)
    released = state not in ["DRAFT", "READY", "LOBBY"] and (
        (eligible and assigned) or (final and state in ["ENDED", "PROVISIONAL", "FINALIZED"])
    )
    tasks = (
        [
            {
                key: value
                for key, value in task.items()
                if key not in ["private_rubric", "prepared_by", "verified_by"]
            }
            for task in round.rules_snapshot.get("coding_tasks", [])
        ]
        if released
        else []
    )
    return {
        "round_id": round.pk,
        "title": round.title,
        "team_code": team.code,
        "session_id": request.team_session.pk,
        "clock": clock_payload(round, now),
        "assigned": assigned,
        "station": station.label if station else None,
        "eligible": eligible,
        "tasks": tasks,
        "responses": [revision_payload(item) for item in latest_revisions(round, team).values()]
        if released
        else [],
        "submission": submission_payload(final) if final and released else None,
        "can_save": bool(released and eligible and assigned and state == "LIVE" and not final),
        "language_versions": round.rules_snapshot.get("rules", {}).get("language_versions", {})
        if released
        else {},
    }


@transaction.atomic
@sensitive_variables("body", "data")
def save_response(request, round_id, task_id, data):
    action_id = attempt_uuid(data.get("action_id"))
    body, language, version = data.get("body"), data.get("language"), data.get("expected_revision")
    if (
        not isinstance(body, str)
        or len(body.encode("utf-8")) > 65536
        or not isinstance(language, str)
        or type(version) is not int
        or version < 0
    ):
        raise ApiProblem(
            "invalid_request", "Supply a response of at most 64 KiB, a language and saved revision."
        )
    team = require_team(request, allow_inactive=True, touch=False)
    round = shared_round(round_id)
    native_round(round, team)
    team = write_team(request)
    fingerprint = {
        "kind": "coding_save",
        "round_id": round_id,
        "team_id": team.pk,
        "task_id": task_id,
        "source_hash": source_hash(body),
        "language": language,
        "expected_revision": version,
    }
    if replay := audit_replay(action_id, fingerprint):
        return replay
    now = database_now()
    live_permission(request, round, team, now)
    if CodingSubmission.objects.filter(round=round, team=team).exists():
        raise ApiProblem(
            "final_locked", "Final work is locked. New responses cannot replace it.", 409
        )
    task = next(
        (item for item in round.rules_snapshot["coding_tasks"] if item["id"] == task_id), None
    )
    if task is None or language not in task["languages"]:
        raise ApiProblem(
            "invalid_request", "Choose a released task and one of its approved languages."
        )
    previous = latest_revisions(round, team).get(task_id)
    if version != (previous.revision if previous else 0):
        raise ApiProblem(
            "stale_revision",
            "This response changed in another tab. Refresh saved work before replacing it.",
            409,
        )
    item = CodingRevision.objects.create(
        round=round,
        team=team,
        task_id=task_id,
        action_id=action_id,
        revision=version + 1,
        language=language,
        body=body,
        source_hash=source_hash(body),
        admitted_at=now,
        active_elapsed_ms=active_elapsed(round, now),
    )
    response = {key: value for key, value in revision_payload(item).items() if key != "body"}
    record_action(
        action_id,
        request.user,
        "save_coding_response",
        "Save acknowledged coding response.",
        fingerprint,
        response,
    )
    return response


def freeze_submission(round, team, when, kind):
    existing = CodingSubmission.objects.filter(round=round, team=team).first()
    if existing:
        return existing
    revisions = latest_revisions(round, team, when)
    manifest = [
        {
            "task_id": item.task_id,
            "revision_id": item.pk,
            "revision": item.revision,
            "source_hash": item.source_hash,
            "language": item.language,
        }
        for item in sorted(revisions.values(), key=lambda item: item.task_id)
    ]
    return CodingSubmission.objects.create(
        round=round,
        team=team,
        kind=kind if manifest else "NO_SUBMISSION",
        submitted_at=when,
        active_elapsed_ms=active_elapsed(round, when),
        manifest=manifest,
        manifest_digest=digest(manifest),
    )


def finalize_at_end(round, when, actor):
    if round.number != 3 or round.delivery_mode != "CODING":
        return
    native_round(round)
    for team in Team.objects.select_for_update().filter(is_demo=round.is_demo).order_by("pk"):
        if CodingSubmission.objects.filter(round=round, team=team).exists():
            continue
        if (
            round_eligible(team, round)
            or CodingRevision.objects.filter(round=round, team=team).exists()
        ):
            final = freeze_submission(round, team, when, "CUTOFF")
            record_action(
                uuid.uuid4(),
                actor,
                "coding_cutoff",
                "Freeze last acknowledged work at cutoff.",
                {"round_id": round.pk, "team_id": team.pk, "cutoff": when.isoformat()},
                submission_payload(final),
            )


@transaction.atomic
def finalize(request, round_id, data):
    action_id = attempt_uuid(data.get("action_id"))
    team = require_team(request, allow_inactive=True, touch=False)
    round = shared_round(round_id)
    native_round(round, team)
    team = write_team(request)
    fingerprint = {**data, "kind": "coding_finalize", "round_id": round_id, "team_id": team.pk}
    if replay := audit_replay(action_id, fingerprint):
        return replay
    now = database_now()
    if round.state == "LIVE" and now > round.deadline_at and round_eligible(team, round):
        final = freeze_submission(round, team, round.deadline_at, "CUTOFF")
    else:
        live_permission(request, round, team, now)
        if CodingSubmission.objects.filter(round=round, team=team).exists():
            raise ApiProblem(
                "final_locked", "Final submission already recorded. Refresh to check it.", 409
            )
        revisions = latest_revisions(round, team)
        expected = {
            str(task["id"]): revisions[task["id"]].revision if task["id"] in revisions else 0
            for task in round.rules_snapshot["coding_tasks"]
        }
        supplied = data.get("expected_revisions")
        if (
            not isinstance(supplied, dict)
            or any(type(value) is not int for value in supplied.values())
            or supplied != expected
        ):
            raise ApiProblem(
                "stale_revision", "Review current response versions before final submission.", 409
            )
        final = freeze_submission(round, team, now, "MANUAL")
    response = submission_payload(final)
    record_action(
        action_id,
        request.user,
        "finalize_coding_submission",
        "Lock final coding work.",
        fingerprint,
        response,
    )
    return response


@transaction.atomic
def assign_workstation(round_id, actor, data):
    require_staff_permission(actor, "control_round")
    action_id, reason = validate_request(data)
    round = locked_round(round_id)
    native_round(round)
    fingerprint = {**data, "kind": "coding_workstation", "round_id": round_id, "actor_id": actor.pk}
    if replay := audit_replay(action_id, fingerprint):
        return replay
    if round.state not in ["READY", "LOBBY", "LIVE", "FROZEN"]:
        raise ApiProblem(
            "invalid_transition", "Assign workstations after READY and before play ends.", 409
        )
    if (
        type(data.get("session_id")) is not int
        or not isinstance(data.get("label"), str)
        or not data["label"].strip()
        or len(data["label"]) > 100
    ):
        raise ApiProblem("invalid_request", "Choose a team browser session and station label.")
    session = (
        TeamSession.objects.select_related("team")
        .filter(
            pk=data["session_id"],
            team__is_demo=round.is_demo,
            revoked_at__isnull=True,
            expires_at__gt=database_now(),
        )
        .first()
    )
    if (
        session is None
        or session.session_version != session.team.session_version
        or not round_eligible(session.team, round)
    ):
        raise ApiProblem("ineligible", "Choose an active, qualified team session.", 403)
    from .corrections import evidence_refs

    old = CodingWorkstation.objects.filter(round=round, team=session.team).first()
    if type(data.get("expected_version")) is not int or data["expected_version"] != (
        old.version if old else 0
    ):
        raise ApiProblem(
            "stale_revision", "The station assignment changed. Refresh before assigning.", 409
        )
    if (
        CodingWorkstation.objects.filter(round=round, label=data["label"])
        .exclude(team=session.team)
        .exists()
    ):
        raise ApiProblem("station_conflict", "That workstation is assigned to another team.", 409)
    station, _ = CodingWorkstation.objects.update_or_create(
        round=round,
        team=session.team,
        defaults={
            "session": session,
            "label": data["label"],
            "supervisor": actor,
            "evidence_references": evidence_refs(data),
            "assigned_at": database_now(),
            "version": old.version + 1 if old else 1,
        },
    )
    response = {
        "station_id": station.pk,
        "team_code": session.team.code,
        "label": station.label,
        "version": station.version,
    }
    record_action(action_id, actor, "assign_coding_workstation", reason, fingerprint, response)
    return response
