"""Host confirmation time is distinct from the participant's buzzer receipt time."""

from django.db import transaction

from .api import ApiProblem
from .buzzer import admission_fence, latest_window, native_round, press_uuid, queue
from .clock import active_elapsed, database_now
from .models import BuzzerAnswerEvidence, BuzzerClosure, BuzzerPress
from .participant import round_eligible
from .results import (
    audit_replay,
    locked_round,
    record_action,
    require_result_role,
    validate_request,
)


def priority_order(window, requested=None, reference=""):
    entries, _ = queue(window)
    codes = [item["team_code"] for item in entries]
    times = {item["team_code"]: item["received_at"] for item in entries}
    tied = len(set(times.values())) != len(times)
    if tied:
        if (
            not isinstance(requested, list)
            or len(requested) != len(codes)
            or any(not isinstance(code, str) for code in requested)
            or set(requested) != set(codes)
            or not isinstance(reference, str)
            or not reference.strip()
            or len(reference) > 200
        ):
            raise ValueError(
                "Equal buzz times need a reviewed order and private adjudication reference."
            )
        if [times[code] for code in requested] != sorted(times.values()):
            raise ValueError("Adjudication cannot reorder different server timestamps.")
        codes = requested
    elif requested:
        raise ValueError("No equal buzzer timestamps require a replacement order.")
    return codes, tied


@transaction.atomic
def record_answer(round_id, actor, data):
    require_result_role(actor)
    if (
        set(data)
        - {
            "action_id",
            "reason",
            "window_id",
            "press_id",
            "verdict",
            "answer",
            "source_reference",
            "buzzer_order",
            "adjudication_reference",
        }
        or type(data.get("window_id")) is not int
    ):
        raise ApiProblem(
            "invalid_request", "Supply only host answer fields; the server records completion time."
        )
    action_id, reason = validate_request(data)
    native_round(round_id)
    admission_fence(round_id, shared=True)
    completed = database_now()
    round = locked_round(round_id)
    fingerprint = {**data, "kind": "buzzer_answer", "round_id": round_id, "actor_id": actor.pk}
    if replay := audit_replay(action_id, fingerprint):
        return replay
    window = latest_window(round)
    if (
        round.state != "LIVE"
        or not round.deadline_at
        or completed >= round.deadline_at
        or window is None
        or window.pk != data.get("window_id")
        or not BuzzerClosure.objects.filter(window=window).exists()
        or window.round_version != round.control_version
    ):
        raise ApiProblem(
            "invalid_transition",
            "Record the offline answer in the current closed question window during live play.",
            409,
        )
    press = (
        BuzzerPress.objects.filter(pk=press_uuid(data.get("press_id")), window=window)
        .select_related("team")
        .first()
    )
    if press is None:
        raise ApiProblem(
            "invalid_press", "Choose the native earliest press for the responding team."
        )
    if not round_eligible(press.team, round):
        raise ApiProblem(
            "not_eligible", "The responding team needs current final qualification.", 403
        )
    try:
        order, tied = priority_order(
            window, data.get("buzzer_order"), data.get("adjudication_reference", "")
        )
    except ValueError as error:
        raise ApiProblem("unresolved_priority", str(error), 409) from None
    entries, _ = queue(window)
    if next(item["id"] for item in entries if item["team_code"] == press.team.code) != str(
        press.pk
    ):
        raise ApiProblem("invalid_press", "Use the team's earliest valid native receipt.")
    prior = {
        item.team.code: item
        for item in BuzzerAnswerEvidence.objects.filter(window=window).select_related("team")
    }
    if press.team.code in prior:
        raise ApiProblem(
            "already_recorded",
            "The original answer is recorded; corrections use reviewed source revisions.",
            409,
        )
    for code in order[: order.index(press.team.code)]:
        if code not in prior or prior[code].verdict not in ["WRONG", "NO_ANSWER"]:
            raise ApiProblem(
                "answer_priority",
                "An earlier buzzing team must answer incorrectly or decline before passing.",
                409,
            )
    if prior and any(item.priority_evidence.get("order") != order for item in prior.values()):
        raise ApiProblem("priority_conflict", "Preserve the original adjudicated queue order.", 409)
    verdict, answer, reference = (
        data.get("verdict"),
        data.get("answer", ""),
        data.get("source_reference"),
    )
    if (
        verdict not in ["CORRECT", "WRONG", "NO_ANSWER"]
        or not isinstance(answer, str)
        or len(answer) > 2000
        or verdict != "NO_ANSWER"
        and not answer.strip()
    ):
        raise ApiProblem(
            "invalid_request",
            "Record the original offline answer and correct/wrong/no-answer verdict.",
        )
    if not isinstance(reference, str) or not reference.strip() or len(reference) > 200:
        raise ApiProblem("evidence_required", "Supply the private host score-sheet reference.")
    item = BuzzerAnswerEvidence.objects.create(
        action_id=action_id,
        window=window,
        team=press.team,
        press=press,
        actor=actor,
        completed_at=completed,
        active_elapsed_ms=active_elapsed(round, completed),
        verdict=verdict,
        answer=answer,
        source_reference=reference,
        priority_evidence={
            "order": order,
            "adjudication_reference": data.get("adjudication_reference", "") if tied else "",
        },
    )
    response = {
        "answer_evidence_id": item.pk,
        "completed_at": item.completed_at.isoformat(timespec="microseconds"),
    }
    record_action(action_id, actor, "record_buzzer_answer", reason, fingerprint, response)
    return response
