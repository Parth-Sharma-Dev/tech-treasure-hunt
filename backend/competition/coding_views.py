from django.http import JsonResponse
from django.views.decorators.http import require_GET, require_POST

from .api import api_errors, json_body
from .coding import assign_workstation, finalize, save_response, workspace


@require_GET
@api_errors
def submission(request, round_id):
    return JsonResponse({"request_id": request.request_id, **workspace(request, round_id)})


@require_POST
@api_errors
def response(request, round_id, task_id):
    return JsonResponse(
        {
            "request_id": request.request_id,
            **save_response(request, round_id, task_id, json_body(request)),
        }
    )


@require_POST
@api_errors
def final(request, round_id):
    return JsonResponse(
        {"request_id": request.request_id, **finalize(request, round_id, json_body(request))}
    )


@require_POST
@api_errors
def station(request, round_id):
    return JsonResponse(
        {
            "request_id": request.request_id,
            **assign_workstation(round_id, request.user, json_body(request)),
        }
    )
