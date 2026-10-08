"""Participant information release is separate from frozen competition rules."""

from django.core.exceptions import ValidationError
from django.db import transaction

from .api import ApiProblem
from .clock import clock_payload, database_now
from .models import (
    AuditEvent,
    Completion,
    EventAnnouncement,
    Incident,
    ResultSnapshot,
    Round,
    RoundInformation,
)
from .participant import public_rules, round_eligible
from .rules import require_staff_permission


def validate_information(info):
    if info.scheduled_start and info.scheduled_end and info.scheduled_end <= info.scheduled_start:
        raise ValidationError("Schedule end must follow its start.")
    if not isinstance(info.contacts, list) or len(info.contacts) > 30:
        raise ValidationError("Supply up to 30 approved contacts as a list.")
    for contact in info.contacts:
        if not isinstance(contact, dict) or set(contact) - {"name", "role", "location", "channel"}:
            raise ValidationError("Contacts support name, role, location and channel only.")
        if any(
            not isinstance(contact.get(key), str) or not contact[key].strip()
            for key in ["name", "role"]
        ):
            raise ValidationError("Each contact needs a name and role.")
        if any(not isinstance(value, str) or len(value) > 200 for value in contact.values()):
            raise ValidationError("Contact values must be text of at most 200 characters.")


@transaction.atomic
def publish_information(model, pk, actor):
    require_staff_permission(actor, "verify_evidence")
    item = model.objects.select_for_update().get(pk=pk)
    if item.prepared_by_id is None or item.prepared_by_id == actor.pk:
        raise ValidationError(
            "A different verifier must review information prepared by an organizer."
        )
    require_staff_permission(item.prepared_by, "prepare_content")
    item.full_clean()
    if isinstance(item, RoundInformation):
        snapshot = {
            "round_id": item.round_id,
            "summary": item.summary,
            "instructions": item.instructions,
            "venue": item.venue,
            "scheduled_start": item.scheduled_start.isoformat() if item.scheduled_start else None,
            "scheduled_end": item.scheduled_end.isoformat() if item.scheduled_end else None,
            "contacts": item.contacts,
            "visible": item.visible,
        }
    else:
        snapshot = {
            "title": item.title,
            "body": item.body,
            "is_demo": item.is_demo,
            "round_id": item.round_id,
            "visible": item.visible,
        }
    old = item.published_snapshot
    item.published_snapshot = snapshot
    item.published_by = actor
    item.published_at = database_now()
    item.save(update_fields=["published_snapshot", "published_by", "published_at"])
    AuditEvent.objects.create(
        actor=actor,
        action="publish_portal_information",
        before={"publication": old},
        after={
            "round_id": item.round_id,
            "model": model._meta.label_lower,
            "id": item.pk,
            "publication": snapshot,
        },
        reason="Independent review and release of participant information.",
    )


def announcements(team, round_id=None):
    notices = []
    for item in EventAnnouncement.objects.filter(
        is_demo=team.is_demo, published_at__isnull=False
    ).order_by("-published_at", "-pk"):
        snapshot = item.published_snapshot
        if snapshot.get("visible") and (
            snapshot.get("round_id") is None or snapshot.get("round_id") == round_id
        ):
            notices.append(
                {"id": item.pk, **snapshot, "published_at": item.published_at.isoformat()}
            )
    return notices


def eligibility_reason(team, round, eligible):
    if round.number == 5:
        return "Round 5 details will be announced later."
    if team.status != "ACTIVE":
        return f"Your team is {team.status.lower()}. Contact an organizer."
    if eligible:
        return "Your team is eligible."
    if Incident.objects.filter(
        round=round, category__in=["RECOVERY", "QUALIFICATION_IMPACT"], closed_at__isnull=True
    ).exists():
        return "Organizer review is required before your team can participate."
    if round.number == 1:
        return "Use the latest Round 1 attempt on your dashboard."
    previous = (
        Round.objects.filter(number=round.number - 1, is_demo=team.is_demo)
        .order_by("-attempt_no")
        .first()
    )
    if previous is None or previous.state != "FINALIZED":
        return f"Eligibility awaits final Round {round.number - 1} results."
    final = ResultSnapshot.objects.filter(round=previous).order_by("-revision").first()
    if final and final.status == "FINAL" and team.code not in final.qualifier_codes:
        return f"Your team did not qualify from Round {round.number - 1}."
    return "Qualification is under organizer review."


def overview(team, round, now=None):
    now = now or database_now()
    clock = clock_payload(round, now)
    eligible = round_eligible(team, round) and round.number != 5
    info = RoundInformation.objects.filter(round=round).first()
    published = info.published_snapshot if info and info.published_snapshot.get("visible") else {}
    if round.number == 5:
        published = {}
    state = clock["state"]
    released = state != "DRAFT" and round.number != 5
    instructions_visible = released and eligible
    information = {key: value for key, value in published.items() if key != "instructions"}
    information["instructions"] = published.get("instructions", "") if instructions_visible else ""
    return {
        "id": round.pk,
        "number": round.number,
        "attempt_no": round.attempt_no,
        "title": round.title,
        "state": state,
        "clock": clock,
        "eligible": eligible,
        "eligibility_reason": eligibility_reason(team, round, eligible),
        "rules": public_rules(round) if released and eligible else None,
        "information": information,
        "announcements": announcements(team, round.pk) if round.number != 5 else [],
        "capabilities": {
            "view_information": round.number != 5,
            "enter_activity": eligible and state == "LIVE",
            "open_mission": eligible
            and state == "LIVE"
            and round.number == 1
            and round.play_mode == "ONLINE",
            "submit_code": False,
            "instructions_visible": instructions_visible,
            "view_results": round.number != 5
            and ResultSnapshot.objects.filter(round=round).exists(),
        },
        "earned_keywords": list(
            Completion.objects.filter(
                team=team,
                mission__round=Round.objects.filter(number=1, is_demo=team.is_demo)
                .order_by("-attempt_no")
                .first(),
                mission__is_practice=False,
                mission__is_void=False,
            ).values_list("mission__keyword", flat=True)
        )
        if round.number == 2 and instructions_visible
        else [],
    }


def dashboard(team):
    now = database_now()
    latest = {}
    for round in Round.objects.filter(is_demo=team.is_demo).order_by("number", "-attempt_no"):
        if round.number not in latest:
            latest[round.number] = overview(team, round, now)
    return {"rounds": list(latest.values()), "announcements": announcements(team)}


def participant_overview(team, round_id):
    round = Round.objects.filter(pk=round_id, is_demo=team.is_demo).first()
    if round is None or round.number == 5:
        raise ApiProblem("not_found", "Round information is not available.", 404)
    latest = (
        Round.objects.filter(number=round.number, is_demo=team.is_demo)
        .order_by("-attempt_no")
        .first()
    )
    if latest.pk != round.pk:
        raise ApiProblem("superseded_attempt", "Open the latest attempt from your dashboard.", 409)
    return overview(team, round)
