"""Database-authoritative active time and serialized, replayable round controls."""

import uuid
from datetime import timedelta

from django.db import IntegrityError, connection, transaction

from .api import ApiProblem
from .models import AuditEvent, Round, RoundPhase
from .rules import require_staff_permission


def database_now():
    # Unlike transaction_timestamp(), this advances while waiting for a row lock.
    with connection.cursor() as cursor:
        cursor.execute("SELECT clock_timestamp()")
        return cursor.fetchone()[0]


def milliseconds(delta):
    return max(0, delta // timedelta(milliseconds=1))


def active_elapsed(round, now):
    elapsed = round.accumulated_active_ms
    if round.state == Round.State.LIVE and round.live_started_at and round.deadline_at:
        elapsed += milliseconds(min(now, round.deadline_at) - round.live_started_at)
    return min(elapsed, round.active_budget_ms)


def clock_payload(round, now):
    elapsed = active_elapsed(round, now)
    expired = (
        round.state == Round.State.LIVE
        and round.deadline_at is not None
        and now > round.deadline_at
    )
    return {
        "round_id": round.pk,
        "state": Round.State.ENDED if expired else round.state,
        "play_mode": round.play_mode,
        "control_version": round.control_version,
        "server_time": now.isoformat(),
        "active_elapsed_ms": elapsed,
        "active_budget_ms": round.active_budget_ms,
        "remaining_ms": max(0, round.active_budget_ms - elapsed),
        "deadline_at": round.deadline_at.isoformat() if round.deadline_at else None,
    }


def close_phase(round, now, actor, reason):
    end = min(now, round.deadline_at) if round.state == Round.State.LIVE else now
    start = round.phase_started_at or round.live_started_at
    if start is None:
        raise ApiProblem("invalid_clock", "This round needs clock reconciliation.", 409)
    RoundPhase.objects.create(
        round=round,
        phase_type=round.state,
        play_mode=round.play_mode,
        started_at=start,
        ended_at=end,
        actor=actor,
        reason=reason,
    )
    if round.state == Round.State.LIVE:
        round.accumulated_active_ms = active_elapsed(round, end)
    round.phase_started_at = None
    round.live_started_at = None
    round.deadline_at = None


@transaction.atomic
def control_round(round_id, actor, data):
    require_staff_permission(actor, "control_round")
    try:
        action_id = uuid.UUID(data.get("action_id"))
    except (ValueError, TypeError, AttributeError):
        raise ApiProblem("invalid_request", "A valid action UUID is required.") from None
    action = data.get("action")
    reason = data.get("reason")
    version = data.get("expected_version")
    extension = data.get("extension_ms", 0)
    if action not in {"open_lobby", "start", "freeze", "resume", "extend", "end"}:
        raise ApiProblem("invalid_request", "Choose a supported round action.")
    if not isinstance(reason, str) or not reason.strip() or len(reason) > 2000:
        raise ApiProblem("invalid_request", "Give a reason for the round action.")
    if type(version) is not int or version < 0:
        raise ApiProblem("invalid_request", "Supply the current control version.")
    if (
        type(extension) is not int
        or (action == "extend" and not 0 < extension <= 86_400_000)
        or (action != "extend" and extension != 0)
    ):
        raise ApiProblem("invalid_request", "Extensions must be positive and at most 24 hours.")
    if Round.objects.filter(pk=round_id, delivery_mode="BUZZER").exists():
        from .buzzer import admission_fence

        admission_fence(round_id)
    round = Round.objects.select_for_update().filter(pk=round_id).first()
    if round is None:
        raise ApiProblem("not_found", "Round not found.", 404)
    fingerprint = {
        "round_id": round_id,
        "actor_id": actor.pk,
        "action": action,
        "reason": reason,
        "expected_version": version,
        "extension_ms": extension,
    }
    previous = AuditEvent.objects.filter(action_id=action_id).first()
    if previous:
        if previous.action != "round_control" or previous.after.get("request") != fingerprint:
            raise ApiProblem("action_conflict", "This action key was used differently.", 409)
        return previous.after["response"]
    if version != round.control_version:
        raise ApiProblem(
            "stale_control", "Round changed. Refresh before applying this action.", 409
        )
    now = database_now()
    before = clock_payload(round, now)
    expired = round.state == Round.State.LIVE and now >= round.deadline_at
    transitions = {
        "open_lobby": {Round.State.READY},
        "start": {Round.State.LOBBY},
        "freeze": {Round.State.LIVE},
        "resume": {Round.State.FROZEN},
        "extend": {Round.State.LIVE, Round.State.FROZEN},
        "end": {Round.State.LIVE, Round.State.FROZEN},
    }
    if round.play_mode != Round.PlayMode.ONLINE:
        raise ApiProblem("paper_mode", "Online controls cannot reopen paper play.", 409)
    if round.number in [2, 3, 4, 5] and action in ["open_lobby", "start"]:
        from .models import Team
        from .participant import round_eligible

        eligible_teams = [
            team
            for team in Team.objects.filter(is_demo=round.is_demo, status="ACTIVE")
            if round_eligible(team, round)
        ]
        if not eligible_teams:
            raise ApiProblem(
                "qualification_pending",
                f"Publish final Round {round.number - 1} qualifiers before opening play.",
                409,
            )
        if round.number == 4:
            from .green_cards import is_green_cards

            assigned = {
                slot["team_code"]
                for panel in round.rules_snapshot.get("rules", {}).get("faculty_panels", [])
                for slot in panel["slots"]
            }
            if not {team.code for team in eligible_teams} <= assigned and not (
                is_green_cards(round)
                and not round.rules_snapshot.get("rules", {}).get("faculty_panels")
            ):
                raise ApiProblem(
                    "assignment_pending", "Every eligible team needs a frozen interview slot.", 409
                )
    if expired:
        from .coding import finalize_at_end

        finalize_at_end(round, round.deadline_at, actor)
        close_phase(round, now, actor, "Active deadline reached: " + reason)
        round.state = Round.State.ENDED
    else:
        if round.state not in transitions[action]:
            raise ApiProblem("invalid_transition", "This action is unavailable in this state.", 409)
        if action == "open_lobby":
            round.state = Round.State.LOBBY
        elif action in {"start", "resume"}:
            if round.accumulated_active_ms >= round.active_budget_ms:
                raise ApiProblem("budget_exhausted", "The active budget is exhausted.", 409)
            if action == "resume":
                close_phase(round, now, actor, reason)
            round.state = Round.State.LIVE
            round.phase_started_at = round.live_started_at = now
            round.deadline_at = now + timedelta(
                milliseconds=round.active_budget_ms - round.accumulated_active_ms
            )
        elif action == "extend":
            round.active_budget_ms += extension
            if round.state == Round.State.LIVE:
                round.deadline_at += timedelta(milliseconds=extension)
        else:
            if action == "end":
                from .coding import finalize_at_end

                finalize_at_end(
                    round, min(now, round.deadline_at) if round.state == "LIVE" else now, actor
                )
            close_phase(round, now, actor, reason)
            round.state = Round.State.FROZEN if action == "freeze" else Round.State.ENDED
            if round.state == Round.State.FROZEN:
                round.phase_started_at = now
    if round.delivery_mode == "BUZZER":
        from .buzzer import close_current_window

        close_current_window(round, actor, "Round control: " + action + ": " + reason, now)
    round.control_version += 1
    round.save()
    response = {**clock_payload(round, now), "deadline_reached": expired}
    try:
        with transaction.atomic():
            AuditEvent.objects.create(
                actor=actor,
                action_id=action_id,
                action="round_control",
                reason=reason,
                before=before,
                after={"request": fingerprint, "response": response},
            )
    except IntegrityError:
        raise ApiProblem("action_conflict", "This action key was already used.", 409) from None
    return response
