import hashlib
import json
import re
from copy import deepcopy

from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.utils import timezone

from .models import AuditEvent, Mission, Round, Team

OWNER_ROLES = ("technical_lead", "content_lead", "operations_lead", "adjudicator", "verifier")
REQUIRED_POLICIES = (
    "allowed_tools",
    "movement_policy",
    "route_reference",
    "accessibility_policy",
    "qualification_tie_policy",
    "appeal_minutes",
    "paper_attempt_policy",
    "unresolved_data_policy",
    "retention_days",
    "delivery_instructions",
    "ranking_policy",
)


def round_snapshot(round):
    return {
        "round_number": round.number,
        "attempt_id": str(round.attempt_id),
        "rules_version": round.rules_version,
        "rules": deepcopy(round.rules),
        "owners": deepcopy(round.owners),
        "delivery_mode": round.delivery_mode,
        "advancement_count": round.advancement_count,
        "active_budget_ms": round.active_budget_ms,
        "title": round.title,
        "is_demo": round.is_demo,
    }


def snapshot_digest(snapshot):
    encoded = json.dumps(
        snapshot, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode()
    return hashlib.sha256(encoded).hexdigest()


def readiness_errors(round):
    errors = []
    if not round.rules_version:
        errors.append("Set a rules version.")
    if round.delivery_mode not in Round.Delivery.values:
        errors.append("Select a delivery method.")
    if round.number == 1 and round.delivery_mode != Round.Delivery.ONLINE_HUNT:
        errors.append("Round 1 requires the online hunt delivery method.")
    if round.number > 1 and round.delivery_mode != Round.Delivery.EXTERNAL:
        errors.append("Rounds 2–5 currently require external delivery.")
    if round.number < 5 and not round.advancement_count:
        errors.append("Set an explicit advancement count.")
    if not isinstance(round.owners, dict):
        return errors + ["Owners must be a role-to-staff mapping."]
    user_model = get_user_model()
    for role in OWNER_ROLES:
        identity = round.owners.get(role)
        if (
            type(identity) is not int
            or not user_model.objects.filter(pk=identity, is_active=True, is_staff=True).exists()
        ):
            errors.append(f"Assign an active staff owner for {role}.")
    if round.owners.get("adjudicator") == round.owners.get("verifier"):
        errors.append("Adjudication and independent verification need different owners.")
    if not isinstance(round.rules, dict):
        return errors + ["Rules must be a configuration object."]
    for policy in REQUIRED_POLICIES:
        value = round.rules.get(policy)
        if value is None or value == "" or value == []:
            errors.append(f"Configure {policy}.")
    tools = round.rules.get("allowed_tools")
    if (
        not isinstance(tools, list)
        or not tools
        or any(not isinstance(tool, str) or not tool.strip() for tool in tools)
    ):
        errors.append("Allowed tools must be an explicit nonempty list; use 'none' if prohibited.")
    for field in ("appeal_minutes", "retention_days"):
        value = round.rules.get(field)
        if type(value) is not int or value <= 0:
            errors.append(f"{field} must be a positive integer.")
    if round.number == 1:
        expected = {
            "points_per_mission": 1,
            "max_team_sessions": 4,
            "answer_format": "four_ascii_digits",
            "free_wrong_attempts": 5,
            "cooldown_seconds": [30, 60, 120, 240, 300],
            "team_answer_limit": 10,
            "team_answer_window_ms": 60_000,
            "cutoff_policy": "database_admission_no_grace",
            "ranking_policy": "score_then_last_active_completion",
            "paper_attempt_policy": "one_per_team_mission_per_60_active_seconds",
        }
        for key, value in expected.items():
            if type(round.rules.get(key)) is not type(value) or round.rules.get(key) != value:
                errors.append(f"Configure the supported Round 1 policy for {key}.")
        cap = round.rules.get("registration_cap")
        browsers = round.rules.get("peak_browser_count")
        if type(cap) is not int or cap <= 0 or type(browsers) is not int or browsers <= 0:
            errors.append("Set separate positive team and peak-browser capacity values.")
        active_teams = Team.objects.filter(status=Team.Status.ACTIVE, is_demo=round.is_demo).count()
        if type(cap) is int and active_teams > cap:
            errors.append("Active roster exceeds the registration cap.")
        if round.advancement_count and active_teams < round.advancement_count:
            if round.rules.get("short_roster_policy") != "advance_all_eligible":
                errors.append(
                    "Choose a short-roster policy before advancing fewer teams than the cut."
                )
        missions = list(Mission.objects.filter(round=round, is_practice=False, available=True))
        expected_count = round.rules.get("expected_mission_count")
        if (
            type(expected_count) is not int
            or expected_count <= 0
            or expected_count != len(missions)
        ):
            errors.append("Confirm the exact count of released competitive missions.")
        if not missions:
            errors.append("Add at least one independently verified competitive mission.")
        for mission in missions:
            staff_ids = (mission.volunteer_owner_id, mission.prepared_by_id, mission.verified_by_id)
            if any(identity is None for identity in staff_ids) or not mission.verified_at:
                errors.append(
                    f"Mission {mission.public_id} needs owners and independent verification."
                )
            elif mission.prepared_by_id == mission.verified_by_id:
                errors.append(f"Mission {mission.public_id} must have an independent verifier.")
            elif user_model.objects.filter(
                pk__in=set(staff_ids), is_active=True, is_staff=True
            ).count() != len(set(staff_ids)):
                errors.append(f"Mission {mission.public_id} owners must be active staff.")
            if mission.is_void:
                errors.append(f"Mission {mission.public_id} is voided; remove it from the release.")
            verifiers = mission.answer_verifiers
            if (
                not isinstance(verifiers, list)
                or not verifiers
                or any(
                    not isinstance(item, dict)
                    or not isinstance(item.get("version"), str)
                    or not item.get("version")
                    or not isinstance(item.get("digest"), str)
                    or re.fullmatch(r"[0-9a-f]{64}", item["digest"]) is None
                    for item in verifiers
                )
            ):
                errors.append(f"Mission {mission.public_id} needs versioned answer verifiers.")
    else:
        if not isinstance(round.rules.get("score_schema"), dict) or not round.rules["score_schema"]:
            errors.append("Set the round-specific score schema and tie metrics.")
    return errors


def require_staff_permission(actor, permission):
    if not actor.is_active or not actor.is_staff or not actor.has_perm(f"competition.{permission}"):
        raise PermissionDenied("This action requires an authorized staff account.")


@transaction.atomic
def approve_rules(round_id, actor):
    require_staff_permission(actor, "verify_evidence")
    round = Round.objects.select_for_update().get(pk=round_id)
    if round.state != Round.State.DRAFT:
        raise ValidationError("Only draft rules can be approved.")
    errors = readiness_errors(round)
    if errors:
        raise ValidationError(errors)
    round.approved_by = actor
    round.approved_at = timezone.now()
    round.approval_digest = snapshot_digest(round_snapshot(round))
    round.save(update_fields=["approved_by", "approved_at", "approval_digest"])
    AuditEvent.objects.create(
        actor=actor,
        action="approve_rules",
        reason="Approve the configured rule snapshot.",
        after={"round_id": round.pk, "approval_digest": round.approval_digest},
    )
    return round


@transaction.atomic
def mark_ready(round_id, actor):
    require_staff_permission(actor, "control_round")
    round = Round.objects.select_for_update().get(pk=round_id)
    if round.state == Round.State.READY:
        return round
    if round.state != Round.State.DRAFT:
        raise ValidationError("Only a draft round can become READY.")
    errors = readiness_errors(round)
    snapshot = round_snapshot(round)
    digest = snapshot_digest(snapshot)
    if not round.approved_by_id or not round.approved_at or round.approval_digest != digest:
        errors.append("The current settings require explicit staff approval.")
    elif (
        not round.approved_by.is_active
        or not round.approved_by.is_staff
        or not round.approved_by.has_perm("competition.verify_evidence")
    ):
        errors.append("The rule approver must remain authorized to verify evidence.")
    if errors:
        raise ValidationError(errors)
    round.rules_snapshot = snapshot
    round.rules_digest = digest
    round.state = Round.State.READY
    round.control_version += 1
    round.save()
    AuditEvent.objects.create(
        actor=actor,
        action="round_ready",
        before={"state": Round.State.DRAFT},
        after={"round_id": round.pk, "state": round.state, "rules_digest": digest},
        reason="Readiness validation passed; freeze the approved configuration.",
    )
    return round
