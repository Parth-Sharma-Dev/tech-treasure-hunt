"""Only independently published contest faculty appear in participant responses."""

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils.dateparse import parse_datetime
from django.utils.timezone import is_aware

from .clock import database_now
from .models import AuditEvent, FacultyProfile, Team
from .rules import require_staff_permission


@transaction.atomic
def publish_faculty(pk, actor):
    require_staff_permission(actor, "verify_evidence")
    item = FacultyProfile.objects.select_for_update().get(pk=pk)
    if not item.prepared_by_id or item.prepared_by_id == actor.pk:
        raise ValidationError(
            "A different verifier must review faculty consent and public details."
        )
    require_staff_permission(item.prepared_by, "prepare_content")
    item.full_clean()
    snapshot = {
        key: getattr(item, key)
        for key in [
            "display_name",
            "role",
            "location",
            "contact_channel",
            "photo_url",
            "is_demo",
            "visible",
        ]
    }
    previous = item.published_snapshot
    item.published_snapshot = snapshot
    item.published_by = actor
    item.published_at = database_now()
    item.save(update_fields=["published_snapshot", "published_by", "published_at"])
    AuditEvent.objects.create(
        actor=actor,
        action="publish_faculty",
        before={"publication": previous},
        after={
            "faculty_id": item.pk,
            "publication": snapshot,
            "consent_reference": item.consent_reference,
        },
        reason="Independent consent and designated contest faculty review.",
    )


def panel_errors(round, panels, frozen=False):
    errors, faculty_seen, team_seen, labels = [], set(), set(), set()
    for panel in panels:
        if not isinstance(panel, dict) or set(panel) != {"label", "faculty_ids", "slots"}:
            errors.append("Panels require label, faculty_ids and slots only.")
            continue
        label, ids, slots = panel["label"], panel["faculty_ids"], panel["slots"]
        if not isinstance(label, str) or not label.strip() or len(label) > 80 or label in labels:
            errors.append("Panel labels must be unique nonempty text of at most 80 characters.")
        else:
            labels.add(label)
        if (
            not isinstance(ids, list)
            or len(ids) != 3
            or any(type(value) is not int or value <= 0 for value in ids)
            or len(set(ids)) != 3
        ):
            errors.append("Each panel requires three distinct faculty IDs.")
            continue
        if faculty_seen.intersection(ids):
            errors.append("Faculty cannot serve on simultaneous panels.")
        faculty_seen.update(ids)
        for identity in ids:
            item = FacultyProfile.objects.filter(pk=identity, is_demo=round.is_demo).first()
            if not frozen and (
                not item
                or not item.published_at
                or not item.published_snapshot.get("visible")
                or item.published_snapshot.get("is_demo") != round.is_demo
            ):
                errors.append(
                    "Every panel member needs an approved visible profile in the same cohort."
                )
        if not isinstance(slots, list) or not slots or len(slots) > 5:
            errors.append("Each panel needs one to five interview slots.")
            continue
        previous_end = None
        for slot in slots:
            try:
                if not isinstance(slot, dict) or set(slot) != {"team_code", "start", "end"}:
                    raise ValueError()
                code = slot["team_code"]
                roster = Team.objects.filter(code=code, is_demo=round.is_demo)
                if (
                    not isinstance(code, str)
                    or code in team_seen
                    or not (roster if frozen else roster.filter(status="ACTIVE")).exists()
                ):
                    raise ValueError()
                start, end = parse_datetime(slot["start"]), parse_datetime(slot["end"])
                if (
                    not start
                    or not end
                    or not is_aware(start)
                    or not is_aware(end)
                    or end <= start
                    or (previous_end and start < previous_end)
                ):
                    raise ValueError()
                if not round.is_demo and (end - start).total_seconds() != 600:
                    raise ValueError()
                previous_end = end
                team_seen.add(code)
            except (ValueError, TypeError):
                errors.append(
                    "Use unique teams and ordered nonoverlapping timezone-aware slots; "
                    "real rounds require ten minutes per slot."
                )
    if not round.is_demo and (len(panels) != 2 or len(team_seen) != 10):
        errors.append("Real Round 4 requires two panels and ten assigned teams.")
    return errors


def participant_faculty(team, round, eligible, state):
    if round.number != 4:
        return {"faculty": [], "interview_assignment": None}
    directory = [
        {"id": item.pk, **item.published_snapshot}
        for item in FacultyProfile.objects.filter(
            is_demo=team.is_demo, published_at__isnull=False
        ).order_by("pk")
        if item.published_snapshot.get("visible")
        and item.published_snapshot.get("is_demo") == team.is_demo
    ]
    assignment = None
    if eligible and state != "DRAFT":
        for panel in round.rules_snapshot.get("rules", {}).get("faculty_panels", []):
            for slot in panel["slots"]:
                if slot["team_code"] == team.code:
                    assignment = {
                        "panel": panel["label"],
                        "faculty_ids": panel["faculty_ids"],
                        "start": slot["start"],
                        "end": slot["end"],
                    }
    return {"faculty": directory, "interview_assignment": assignment}
