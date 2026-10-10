"""Online mission access and durable decisions under Round -> Team locks."""

import hmac
import json
import uuid

from django.conf import settings
from django.core.signing import Signer
from django.db import connection, transaction
from django.utils.crypto import salted_hmac
from django.views.decorators.debug import sensitive_variables

from .answers import answer_digest
from .api import ApiProblem
from .clock import active_elapsed, clock_payload, database_now
from .models import AttemptState, Completion, Mission, Round, SubmissionDecision, Team, Visit
from .participant import round_eligible
from .sessions import require_team


def shared_round(round_id):
    with connection.cursor() as cursor:
        cursor.execute("SELECT id FROM competition_round WHERE id = %s FOR SHARE", [round_id])
        if cursor.fetchone() is None:
            raise ApiProblem("not_found", "Round not found.", 404)
    return Round.objects.get(pk=round_id)


def find_mission(token=None, fallback=None):
    query = Mission.objects.filter(is_practice=False)
    mission = (
        query.filter(token=token).first() if token else query.filter(fallback_code=fallback).first()
    )
    if mission is None:
        raise ApiProblem("not_found", "Mission not found. Check the QR link or fallback code.", 404)
    return mission


def write_team(request):
    identity = require_team(request, allow_inactive=True, touch=False)
    Team.objects.select_for_update().get(pk=identity.pk)
    # Recheck the cookie, revocation, team status and version after lock waits.
    return require_team(request, allow_inactive=True)


def mission_payload(mission, team, round, now):
    from .answers import answer_format

    opened = Visit.objects.filter(team=team, mission=mission).exists()
    completion = Completion.objects.filter(team=team, mission=mission).first()
    attempt = AttemptState.objects.filter(team=team, mission=mission).first()
    visible = opened and round.state not in {
        Round.State.DRAFT,
        Round.State.READY,
        Round.State.LOBBY,
    }
    return {
        "team_code": team.code,
        "token": mission.token,
        "mission_id": mission.public_id,
        "round_id": round.pk,
        "answer_format": answer_format(round),
        "clock": clock_payload(round, now),
        "opened": opened,
        "hint": mission.hint if visible else None,
        "symbol": mission.symbol if visible else None,
        "completed": completion is not None,
        "voided": mission.is_void,
        "keyword": mission.keyword if completion else None,
        "wrong_count": attempt.evaluated_wrong_count if attempt else 0,
        "cooldown_remaining_ms": max(
            0, attempt.cooldown_until_active_ms - active_elapsed(round, now)
        )
        if attempt
        else 0,
    }


def mission_read(request, token):
    team = require_team(request, allow_inactive=True)
    mission = find_mission(token=token)
    round = Round.objects.get(pk=mission.round_id)
    if team.is_demo != round.is_demo:
        raise ApiProblem("not_found", "Mission not found.", 404)
    return mission_payload(mission, team, round, database_now())


@transaction.atomic
def open_mission(request, data):
    token, fallback = data.get("token"), data.get("fallback_code")
    if (
        bool(token) == bool(fallback)
        or (token and not isinstance(token, str))
        or (fallback and not isinstance(fallback, str))
    ):
        raise ApiProblem("invalid_request", "Supply one QR token or fallback code.")
    mission = find_mission(token=token, fallback=fallback.strip().upper() if fallback else None)
    round = shared_round(mission.round_id)
    team = write_team(request)
    mission.refresh_from_db()
    now = database_now()
    if round.number != 1 or round.delivery_mode != Round.Delivery.ONLINE_HUNT:
        raise ApiProblem(
            "external_delivery",
            "This round is externally judged; native mission access is unavailable.",
            409,
        )
    if not round_eligible(team, round):
        raise ApiProblem("ineligible", "Your team is not eligible for this round.", 403)
    if round.state != "LIVE" or round.play_mode != "ONLINE" or now > round.deadline_at:
        raise ApiProblem("round_closed", "New clues open only during live online play.", 409)
    if not mission.available or mission.is_void:
        raise ApiProblem("mission_unavailable", "This mission is unavailable.", 409)
    visit, created = Visit.objects.get_or_create(
        team=team,
        mission=mission,
        defaults={
            "first_opened_at": now,
            "last_opened_at": now,
            "access_method": "QR" if token else "FALLBACK",
        },
    )
    if not created:
        visit.last_opened_at = now
        visit.count += 1
        visit.save(update_fields=["last_opened_at", "count"])
    return mission_payload(mission, team, round, now)


def request_fingerprint(mission, answer):
    payload = json.dumps(
        {"endpoint": "submit", "mission": mission.pk, "answer": answer}, sort_keys=True
    )
    return salted_hmac(
        "competition.submission-request.v1",
        payload,
        secret=settings.ANSWER_HMAC_KEY,
        algorithm="sha256",
    ).hexdigest()


def replay(team, round_id, key, fingerprint):
    decision = SubmissionDecision.objects.filter(
        team=team, round_id=round_id, idempotency_key=key
    ).first()
    if decision:
        if not hmac.compare_digest(decision.request_fingerprint, fingerprint):
            raise ApiProblem(
                "idempotency_conflict",
                "This attempt ID was used for a different answer or mission.",
                409,
            )
        return decision.response_snapshot
    return None


def attempt_uuid(value):
    try:
        return uuid.UUID(value)
    except (ValueError, TypeError, AttributeError):
        raise ApiProblem("invalid_request", "Supply a valid attempt UUID.") from None


@transaction.atomic
@sensitive_variables("answer", "data")
def submit_answer(request, token, key_value, data):
    key = attempt_uuid(key_value)
    answer = data.get("answer")
    team = require_team(request, allow_inactive=True, touch=False)
    mission = find_mission(token=token)
    from .answers import validate_answer

    answer = validate_answer(mission.round, answer)
    if mission.round.is_demo != team.is_demo:
        raise ApiProblem("not_found", "Mission not found.", 404)
    fingerprint = request_fingerprint(mission, answer)
    if original := replay(team, mission.round_id, key, fingerprint):
        return original
    round = shared_round(mission.round_id)
    team = write_team(request)
    mission.refresh_from_db()
    if original := replay(team, round.pk, key, fingerprint):
        return original
    now = database_now()
    elapsed = active_elapsed(round, now)
    outcome, cooldown_remaining = None, 0
    if round.number != 1 or round.delivery_mode != Round.Delivery.ONLINE_HUNT:
        outcome = "external_delivery"
    elif not round_eligible(team, round):
        outcome = "ineligible"
    elif round.play_mode != "ONLINE":
        outcome = "paper_mode"
    elif round.state != "LIVE":
        outcome = "paused" if round.state == "FROZEN" else "round_closed"
    elif now > round.deadline_at:
        outcome = "late"
    elif not mission.available or mission.is_void:
        outcome = "mission_unavailable"
    elif not Visit.objects.filter(team=team, mission=mission).exists():
        outcome = "not_opened"
    elif Completion.objects.filter(team=team, mission=mission).exists():
        outcome = "already_completed"
    attempt = None
    answer_hmac, answer_version = "", ""
    if outcome is None:
        rules = round.rules_snapshot["rules"]
        attempt, _ = AttemptState.objects.get_or_create(team=team, mission=mission)
        cooldown_remaining = max(0, attempt.cooldown_until_active_ms - elapsed)
        recent = SubmissionDecision.objects.filter(
            team=team,
            round=round,
            outcome__in=["accepted", "incorrect"],
            active_elapsed_ms__gt=elapsed - rules["team_answer_window_ms"],
            active_elapsed_ms__lte=elapsed,
        ).count()
        if cooldown_remaining:
            outcome = "cooldown"
        elif recent >= rules["team_answer_limit"]:
            outcome = "throttled"
        else:
            outcome = "incorrect"
            for verifier in mission.answer_verifiers:
                digest = answer_digest(mission.pk, verifier["version"], answer)
                if not answer_hmac:
                    answer_hmac, answer_version = digest, verifier["version"]
                if hmac.compare_digest(digest, verifier["digest"]):
                    outcome = "accepted"
                    answer_hmac, answer_version = digest, verifier["version"]
            if outcome == "incorrect":
                attempt.evaluated_wrong_count += 1
                index = attempt.evaluated_wrong_count - rules["free_wrong_attempts"] - 1
                if index >= 0:
                    cooldown_remaining = (
                        rules["cooldown_seconds"][min(index, len(rules["cooldown_seconds"]) - 1)]
                        * 1000
                    )
                    attempt.cooldown_until_active_ms = elapsed + cooldown_remaining
                attempt.save()
    decision_id = uuid.uuid4()
    response = {
        "idempotency_key": str(key),
        "decision_id": str(decision_id),
        "mission_id": mission.public_id,
        "round_id": round.pk,
        "outcome": outcome,
        "admitted_at": now.isoformat(),
        "active_elapsed_ms": elapsed,
        "points_awarded": 1 if outcome == "accepted" else 0,
        "keyword": mission.keyword if outcome in {"accepted", "already_completed"} else None,
        "cooldown_remaining_ms": cooldown_remaining,
        "wrong_count": attempt.evaluated_wrong_count if attempt else 0,
    }
    if outcome == "accepted":
        response["receipt"] = Signer(salt="competition.accepted-receipt.v1").sign_object(
            {
                **response,
                "team_code": team.code,
                "attempt_id": str(round.attempt_id),
                "rules_version": round.rules_version,
            }
        )
    decision = SubmissionDecision.objects.create(
        id=decision_id,
        team=team,
        round=round,
        mission=mission,
        idempotency_key=key,
        request_fingerprint=fingerprint,
        answer_hmac=answer_hmac,
        ingress_at=request.ingress_at,
        admitted_at=now,
        active_elapsed_ms=elapsed,
        rules_version=round.rules_version,
        answer_key_version=answer_version,
        outcome=outcome,
        response_snapshot=response,
    )
    if outcome == "accepted":
        Completion.objects.create(
            team=team,
            mission=mission,
            source_decision=decision,
            effective_at=now,
            effective_active_ms=elapsed,
        )
    return response


def own_progress(team, round):
    completions = Completion.objects.filter(team=team, mission__round=round).select_related(
        "mission"
    )
    return {
        "score": sum(not item.mission.is_void for item in completions),
        "completions": [
            {
                "mission_id": item.mission.public_id,
                "keyword": item.mission.keyword,
                "voided": item.mission.is_void,
            }
            for item in completions
        ],
    }
