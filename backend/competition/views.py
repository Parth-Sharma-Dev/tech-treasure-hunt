from django.http import JsonResponse
from django.middleware.csrf import get_token
from django.views.decorators.debug import sensitive_post_parameters
from django.views.decorators.http import require_GET, require_POST

from .api import ApiProblem, api_errors, json_body
from .clock import clock_payload, control_round, database_now
from .models import Round
from .participant import participant_rounds, practice_answer, practice_mission
from .rules import require_staff_permission
from .sessions import (
    MAX_TEAM_SESSIONS,
    active_sessions,
    login_team,
    logout_team,
    require_team,
    revoke_session,
    safe_return_path,
)


def team_payload(request, team):
    return {
        "request_id": request.request_id,
        "team": {
            "code": team.code,
            "name": team.name,
            "member_count": team.member_count,
            "status": team.status,
            "is_demo": team.is_demo,
        },
        "session": {"active_count": active_sessions(team).count(), "max_active": MAX_TEAM_SESSIONS},
        "rounds": participant_rounds(team),
    }


@require_POST
@api_errors
@sensitive_post_parameters("password")
def team_login(request):
    data = json_body(request)
    code, password = data.get("team_code"), data.get("password")
    if (
        not isinstance(code, str)
        or not isinstance(password, str)
        or not code.strip()
        or len(code) > 24
        or not password
        or len(password) > 256
    ):
        raise ApiProblem("invalid_request", "Enter your team code and password.")
    result = login_team(request, code.strip().upper(), password)
    if isinstance(result, ApiProblem):
        raise result
    payload = team_payload(request, result)
    payload.update(
        {"return_to": safe_return_path(data.get("return_to")), "csrf_token": get_token(request)}
    )
    return JsonResponse(payload)


@require_POST
@api_errors
def team_logout(request):
    logout_team(request)
    return JsonResponse(
        {"request_id": request.request_id, "signed_out": True, "csrf_token": get_token(request)}
    )


@require_GET
@api_errors
def me(request):
    team = require_team(request, allow_inactive=True)
    return JsonResponse(team_payload(request, team))


@require_GET
@api_errors
def practice(request):
    mission = practice_mission(require_team(request))
    return JsonResponse(
        {
            "request_id": request.request_id,
            "hint": mission.hint,
            "symbol": mission.symbol,
            "practice_only": True,
        }
    )


@require_POST
@api_errors
@sensitive_post_parameters("answer")
def submit_practice(request):
    data = json_body(request)
    return JsonResponse(
        {
            "request_id": request.request_id,
            **practice_answer(require_team(request), data.get("answer")),
        }
    )


@require_POST
@api_errors
def staff_revoke_session(request, team_id, session_id):
    data = json_body(request)
    response = revoke_session(
        team_id, session_id, request.user, data.get("action_id"), data.get("reason")
    )
    return JsonResponse({"request_id": request.request_id, **response})


@require_GET
@api_errors
def staff_rounds(request):
    require_staff_permission(request.user, "control_round")
    now = database_now()
    return JsonResponse(
        {
            "rounds": [
                {
                    "title": round.title,
                    "number": round.number,
                    "is_demo": round.is_demo,
                    **clock_payload(round, now),
                }
                for round in Round.objects.order_by("number", "-attempt_no")
            ],
            "request_id": request.request_id,
        }
    )


@require_POST
@api_errors
def staff_control_round(request, round_id):
    response = control_round(round_id, request.user, json_body(request))
    return JsonResponse({"request_id": request.request_id, **response})
