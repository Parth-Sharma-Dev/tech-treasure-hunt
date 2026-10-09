"""Database-timed buzzes; a shared admission fence drains before staff closure."""

from uuid import UUID

from django.db import IntegrityError, connection, transaction

from .api import ApiProblem
from .buzzer_content import questions_snapshot
from .clock import clock_payload, database_now
from .models import BuzzerClosure, BuzzerPress, BuzzerWindow, Round, Team, TeamSession
from .participant import round_eligible
from .portal import eligibility_reason
from .results import (
    audit_replay,
    has_role,
    locked_round,
    record_action,
    require_result_view,
    validate_request,
)
from .rules import require_staff_permission, snapshot_digest
from .sessions import require_team


def admission_fence(round_id, *, shared=False, wait=False):
    with connection.cursor() as cursor:
        if shared and wait:
            cursor.execute("SELECT pg_advisory_xact_lock_shared(%s, %s)", [1075, round_id])
        elif shared:
            cursor.execute("SELECT pg_try_advisory_xact_lock_shared(%s, %s)", [1075, round_id])
            if not cursor.fetchone()[0]:
                raise ApiProblem(
                    "buzzer_transition",
                    "The organizer is changing the buzzer window. Refresh its status.",
                    409,
                )
        else:
            cursor.execute("SELECT pg_advisory_xact_lock(%s, %s)", [1075, round_id])


def native_round(round_id, team=None):
    round = Round.objects.filter(pk=round_id, number=5, delivery_mode="BUZZER").first()
    if round is None or team and round.is_demo != team.is_demo:
        raise ApiProblem("not_found", "Buzzer round not found.", 404)
    return round


def latest_window(round):
    return (
        BuzzerWindow.objects.filter(round=round)
        .select_related("question")
        .order_by("-version")
        .first()
    )


def is_open(round, window, now):
    return bool(
        window
        and window.round_version == round.control_version
        and round.state == "LIVE"
        and round.deadline_at
        and now < round.deadline_at
        and window.opened_at <= now
        and not BuzzerClosure.objects.filter(window=window).exists()
    )


def window_payload(round, window, now):
    if window is None:
        return None
    closure = BuzzerClosure.objects.filter(window=window).first()
    return {
        "id": window.pk,
        "version": window.version,
        "stage": window.question.stage,
        "question_id": window.question_id,
        "question_label": window.question.public_id,
        "opened_at": window.opened_at.isoformat(),
        "closed_at": closure.closed_at.isoformat() if closure else None,
        "accepting": is_open(round, window, now),
    }


def press_payload(item):
    return {
        "id": str(item.pk),
        "window_id": item.window_id,
        "received_at": item.received_at.isoformat(timespec="microseconds"),
        "admitted_at": item.admitted_at.isoformat(timespec="microseconds"),
    }


def earliest_press(window, team):
    return (
        BuzzerPress.objects.filter(window=window, team=team).order_by("received_at", "id").first()
    )


def queue(window):
    if window is None:
        return [], []
    # DISTINCT ON chooses one earliest immutable receipt per team; UUID orders display only.
    candidates = list(
        BuzzerPress.objects.filter(window=window)
        .select_related("team")
        .order_by("team_id", "received_at", "id")
        .distinct("team_id")
    )
    candidates.sort(key=lambda item: (item.received_at, item.team.code))
    first = [item.team.code for item in candidates if item.received_at == candidates[0].received_at]
    return [
        {
            **press_payload(item),
            "team_code": item.team.code,
            "team_name": item.team.name,
            "team_status": item.team.status,
            "position": 1 + sum(other.received_at < item.received_at for other in candidates),
        }
        for item in candidates
    ], first


def participant_status(request, round_id):
    team = require_team(request, allow_inactive=True, touch=False)
    round = native_round(round_id, team)
    latest = Round.objects.filter(number=5, is_demo=team.is_demo).order_by("-attempt_no").first()
    if latest.pk != round.pk:
        raise ApiProblem(
            "superseded_attempt", "Open the latest Round 5 attempt from the dashboard.", 409
        )
    now = database_now()
    eligible = round_eligible(team, round)
    window = latest_window(round) if eligible and round.state != "DRAFT" else None
    own = earliest_press(window, team) if window else None
    return {
        "round_id": round.pk,
        "team_code": team.code,
        "state": clock_payload(round, now)["state"],
        "eligible": eligible,
        "eligibility_reason": eligibility_reason(team, round, eligible),
        "window": window_payload(round, window, now),
        "own_press": press_payload(own) if own else None,
        "can_press": eligible and is_open(round, window, now) and own is None,
    }


def press_uuid(value):
    try:
        return UUID(value)
    except (TypeError, ValueError, AttributeError):
        raise ApiProblem("invalid_request", "Supply the original press UUID.") from None


def recorded_press(request, round_id, identity):
    team = require_team(request, allow_inactive=True, touch=False)
    native_round(round_id, team)
    item = BuzzerPress.objects.filter(
        pk=press_uuid(identity), team=team, window__round_id=round_id
    ).first()
    if item is None:
        raise ApiProblem("not_found", "This press has not been recorded.", 404)
    return {"press": press_payload(item)}


def lock_press_team(team_id):
    return Team.objects.select_for_update().get(pk=team_id)


@transaction.atomic
def press(request, round_id, data):
    if set(data) != {"action_id", "window_id"} or type(data.get("window_id")) is not int:
        raise ApiProblem(
            "invalid_request",
            "Supply only press UUID and current window ID; the server records time and team.",
        )
    identity = press_uuid(data.get("action_id"))
    team = require_team(request, allow_inactive=True, touch=False)
    native_round(round_id, team)
    if existing := BuzzerPress.objects.filter(pk=identity).first():
        if (
            existing.team_id != team.pk
            or existing.window_id != data["window_id"]
            or existing.window.round_id != round_id
        ):
            raise ApiProblem("action_conflict", "This press ID was used differently.", 409)
        return {"press": press_payload(existing)}
    admission_fence(round_id, shared=True)
    received = database_now()  # Single PostgreSQL clock, before any contended team lock.
    team = lock_press_team(team.pk)
    # Team restrictions, session revocation and qualification changes serialize on this lock.
    session = TeamSession.objects.filter(
        pk=request.team_session.pk,
        team=team,
        revoked_at__isnull=True,
        session_version=team.session_version,
        expires_at__gt=database_now(),
    ).first()
    if session is None:
        raise ApiProblem("session_revoked", "Your session has ended. Sign in again.", 401)
    if existing := BuzzerPress.objects.filter(pk=identity).first():
        if existing.team_id != team.pk or existing.window_id != data["window_id"]:
            raise ApiProblem("action_conflict", "This press ID was used differently.", 409)
        return {"press": press_payload(existing)}
    round = native_round(round_id, team)
    if not round_eligible(team, round):
        raise ApiProblem("not_eligible", eligibility_reason(team, round, False), 403)
    window = latest_window(round)
    if window is None or window.pk != data["window_id"] or not is_open(round, window, received):
        raise ApiProblem(
            "buzzer_closed",
            "This question's buzzer is closed, paused or has changed. Refresh its status.",
            409,
        )
    try:
        with transaction.atomic():
            item = BuzzerPress.objects.create(
                id=identity,
                window=window,
                team=team,
                session=session,
                received_at=received,
                admitted_at=database_now(),
            )
    except IntegrityError:
        raise ApiProblem(
            "action_conflict", "This press ID was already used. Refresh its recorded outcome.", 409
        ) from None
    return {"press": press_payload(item)}


def close_current_window(round, actor, reason, now=None):
    window = latest_window(round)
    if window and not BuzzerClosure.objects.filter(window=window).exists():
        BuzzerClosure.objects.create(
            window=window, actor=actor, reason=reason, closed_at=now or database_now()
        )


@transaction.atomic
def control_window(round_id, actor, data):
    require_staff_permission(actor, "control_round")
    action_id, reason = validate_request(data)
    if data.get("operation") not in ["open", "close"]:
        raise ApiProblem("invalid_request", "Choose open or close buzzer.")
    native_round(round_id)
    admission_fence(round_id)
    round = locked_round(round_id)
    native_round(round_id)
    fingerprint = {**data, "round_id": round_id, "actor_id": actor.pk, "kind": "buzzer_control"}
    if original := audit_replay(action_id, fingerprint):
        return original
    window = latest_window(round)
    if (
        type(data.get("expected_version")) is not int
        or data["expected_version"] != round.control_version
        or type(data.get("expected_window_version")) is not int
        or data["expected_window_version"] != (window.version if window else 0)
    ):
        raise ApiProblem(
            "stale_control", "Refresh the round and buzzer window before applying this action.", 409
        )
    now = database_now()
    if data["operation"] == "close":
        if window is None or BuzzerClosure.objects.filter(window=window).exists():
            raise ApiProblem("buzzer_closed", "No open buzzer window remains.", 409)
        close_current_window(round, actor, reason, now)
    else:
        if round.state != "LIVE" or not round.deadline_at or now >= round.deadline_at:
            raise ApiProblem(
                "invalid_transition", "Start/resume Round 5 before opening a buzzer window.", 409
            )
        if window and is_open(round, window, now):
            raise ApiProblem(
                "window_open", "Close the current question before opening another.", 409
            )
        if snapshot_digest(round.rules_snapshot) != round.rules_digest or questions_snapshot(
            round
        ) != round.rules_snapshot.get("buzzer_questions"):
            raise ApiProblem(
                "evidence_gap", "The frozen question/rule evidence needs organizer review.", 409
            )
        if not any(
            round_eligible(team, round) for team in Team.objects.filter(is_demo=round.is_demo)
        ):
            raise ApiProblem("qualification_pending", "Final Round 4 qualifiers are required.", 409)
        question_id = data.get("question_id")
        if type(question_id) is not int or question_id not in {
            item["id"] for item in round.rules_snapshot["buzzer_questions"]
        }:
            raise ApiProblem("invalid_request", "Choose a frozen question in this Round 5 attempt.")
        close_current_window(round, actor, "Superseded stale window: " + reason, now)
        window = BuzzerWindow.objects.create(
            round=round,
            question_id=question_id,
            version=window.version + 1 if window else 1,
            round_version=round.control_version,
            actor=actor,
            reason=reason,
            opened_at=now,
        )
    entries, first = queue(window)
    response = {
        "window": window_payload(round, window, now),
        "entries": entries,
        "first_team_codes": first,
    }
    record_action(action_id, actor, "buzzer_control", reason, fingerprint, response)
    return response


@transaction.atomic
def staff_desk(round_id, actor):
    require_result_view(actor)
    native_round(round_id)
    admission_fence(round_id, shared=True, wait=True)
    round = native_round(round_id)
    now = database_now()
    window = latest_window(round)
    entries, first = queue(window)
    history = list(
        BuzzerWindow.objects.filter(round=round)
        .select_related("question")
        .order_by("-version")[:100]
    )
    return {
        "round_id": round.pk,
        "title": round.title,
        "state": clock_payload(round, now)["state"],
        "control_version": round.control_version,
        "can_control": has_role(actor, "control_round"),
        "window": window_payload(round, window, now),
        "entries": entries,
        "first_team_codes": first,
        "timestamp_tie": len(first) > 1,
        "order_final": bool(window and BuzzerClosure.objects.filter(window=window).exists()),
        "questions": [
            {key: item[key] for key in ["id", "stage", "public_id", "version"]}
            for item in round.rules_snapshot.get("buzzer_questions", [])
        ],
        "history": [
            {"window": window_payload(round, item, now), "entries": queue(item)[0]}
            for item in history
        ],
    }
