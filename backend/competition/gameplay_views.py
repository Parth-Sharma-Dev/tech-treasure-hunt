from django.http import JsonResponse
from django.views.decorators.debug import sensitive_post_parameters
from django.views.decorators.http import require_GET, require_POST

from .api import ApiProblem, api_errors, json_body
from .clock import clock_payload, database_now
from .gameplay import attempt_uuid, mission_read, open_mission, own_progress, submit_answer
from .models import Round, SubmissionDecision
from .sessions import require_team


@require_GET
@api_errors
def mission(request, token):
    return JsonResponse({"request_id": request.request_id, **mission_read(request, token)})


@require_POST
@api_errors
def open(request):
    return JsonResponse(
        {"request_id": request.request_id, **open_mission(request, json_body(request))}
    )


@require_POST
@api_errors
@sensitive_post_parameters("answer")
def submit(request, token):
    response = submit_answer(
        request, token, request.headers.get("Idempotency-Key"), json_body(request)
    )
    return JsonResponse({"request_id": request.request_id, **response})


@require_GET
@api_errors
def state(request, round_id):
    team = require_team(request, allow_inactive=True)
    round = Round.objects.filter(pk=round_id, is_demo=team.is_demo).first()
    if round is None:
        raise ApiProblem("not_found", "Round not found.", 404)
    return JsonResponse(
        {
            "request_id": request.request_id,
            **clock_payload(round, database_now()),
            **own_progress(team, round),
        }
    )


@require_GET
@api_errors
def attempt(request, round_id, key):
    team = require_team(request, allow_inactive=True)
    decision = SubmissionDecision.objects.filter(
        team=team, round_id=round_id, idempotency_key=attempt_uuid(key)
    ).first()
    return JsonResponse(
        {
            "request_id": request.request_id,
            "status": "recorded" if decision else "unknown",
            "decision": decision.response_snapshot if decision else None,
        }
    )


@require_GET
@api_errors
def receipts(request):
    team = require_team(request, allow_inactive=True)
    return JsonResponse(
        {
            "request_id": request.request_id,
            "receipts": [
                decision.response_snapshot
                for decision in SubmissionDecision.objects.filter(
                    team=team, outcome="accepted"
                ).order_by("admitted_at")
            ],
        }
    )
