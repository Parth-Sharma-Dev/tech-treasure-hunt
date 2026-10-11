"""Private, atomic official-roster and credential import using normal review services."""

import csv
import uuid
from pathlib import Path

from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.core.management.base import CommandError
from django.core.validators import validate_email
from django.db import transaction
from django.views.decorators.debug import sensitive_variables

from .models import AuditEvent, Team
from .roster import credentials, locked_roster, propose_roster, review_roster
from .rules import require_staff_permission

HEADERS = ["Team ID", "Leader Name", "Leader Email", "Password"]


@sensitive_variables()
def read_private_roster(path, member_count, expected_count):
    path = Path(path)
    if path.stat().st_size > 1_000_000:
        raise CommandError("Private credential CSV must be at most 1 MB.")
    with path.open(encoding="utf-8-sig", newline="") as source:
        reader = csv.DictReader(source, strict=True)
        if reader.fieldnames != HEADERS:
            raise CommandError("Required CSV columns: " + ",".join(HEADERS))
        entries = list(reader)
    if not 1 <= expected_count <= 500 or len(entries) != expected_count:
        raise CommandError(f"Expected exactly {expected_count} official team rows.")
    if member_count not in (3, 4):
        raise CommandError("Use an organizer-confirmed member count of 3 or 4.")
    users, rows, secrets = get_user_model(), [], []
    for index, entry in enumerate(entries, 1):
        if None in entry or any(value is None for value in entry.values()):
            raise CommandError(f"Malformed private CSV row {index}.")
        code = entry["Team ID"].strip()
        email = entry["Leader Email"].strip()
        password = entry["Password"]  # Never trim/alter the supplied password.
        if not 8 <= len(password) <= 128:
            raise CommandError(f"Row {index}: password must have 8–128 characters.")
        try:
            validate_email(email)
            validate_password(password, users(username=code, email=email))
        except ValidationError as error:
            codes = sorted({item.code or "invalid" for item in error.error_list})
            raise CommandError(f"Row {index}: validation failed ({','.join(codes)}).") from None
        rows.append(
            {
                "code": code,
                "name": f"Team {code}",
                "leader_name": entry["Leader Name"].strip(),
                "member_count": member_count,
                "roster_reference": f"official-roster:{path.name}:row-{index}",
                "status": "ACTIVE",
            }
        )
        secrets.append({"email": email, "password": password})
    return rows, secrets


def action(reason, **data):
    return {"action_id": str(uuid.uuid4()), "reason": reason, **data}


@transaction.atomic
@sensitive_variables()
def import_teams(path, actor, verifier, member_count, expected_count=110, dry_run=False):
    require_staff_permission(actor, "control_round")
    require_staff_permission(verifier, "verify_evidence")
    if actor.pk == verifier.pk:
        raise CommandError("Roster review needs a different authorized verifier.")
    rows, secrets = read_private_roster(path, member_count, expected_count)
    rounds, existing = locked_roster(False)
    if any(round.state != "DRAFT" for round in rounds):
        raise CommandError("Import the official roster before releasing any real round.")
    if any(team.code not in {row["code"] for row in rows} for team in existing):
        raise CommandError("Additional real teams exist outside this list; review them separately.")
    reason = f"Import organizer-supplied official roster; all teams have {member_count} members."
    proposal = propose_roster(actor, action(reason, is_demo=False, rows=rows))
    review_roster(
        verifier, action(reason, proposal_id=proposal["proposal_id"], evidence_confirmed=True)
    )
    for index, (row, private) in enumerate(zip(rows, secrets, strict=True), 1):
        team = Team.objects.select_for_update().select_related("user").get(code=row["code"])
        if team.user.is_staff or team.user.is_superuser or not team.user.is_active:
            raise CommandError(f"Row {index}: an existing account is not an active participant.")
        team.user.email = private["email"]
        team.user.full_clean(exclude=["password"])
        team.user.save(update_fields=["email"])
        # The existing service uses set_password, validates strength, revokes old
        # sessions and records only a keyed password fingerprint in the audit trail.
        credentials(
            actor,
            team.pk,
            action(reason, password=private["password"], expected_version=team.session_version),
        )
        team.user.refresh_from_db()
        if not team.user.check_password(private["password"]):
            raise CommandError(f"Row {index}: credential read-back verification failed.")
    AuditEvent.objects.create(
        actor=actor,
        action="import_official_team_credentials",
        after={
            "team_count": len(rows),
            "member_count": member_count,
            "verifier_id": verifier.pk,
            "roster_proposal_id": proposal["proposal_id"],
        },
        reason=reason,
    )
    if dry_run:
        transaction.set_rollback(True)
    return len(rows)
