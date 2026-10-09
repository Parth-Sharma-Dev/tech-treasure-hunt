from django.http import JsonResponse
from django.views.decorators.http import require_GET, require_POST

from . import buzzer
from .api import api_errors, json_body
from .models import Round
from .results import require_result_view


@require_GET
@api_errors
def status(request, round_id):
    return JsonResponse(buzzer.participant_status(request, round_id))


@require_POST
@api_errors
def press(request, round_id):
    return JsonResponse(buzzer.press(request, round_id, json_body(request)))


@require_GET
@api_errors
def receipt(request, round_id, identity):
    return JsonResponse(buzzer.recorded_press(request, round_id, identity))


@require_GET
@api_errors
def rounds(request):
    require_result_view(request.user)
    return JsonResponse(
        {
            "rounds": list(
                Round.objects.filter(number=5, delivery_mode="BUZZER")
                .order_by("-attempt_no")
                .values("id", "title", "attempt_no", "state", "is_demo")
            )
        }
    )


@require_GET
@api_errors
def desk(request, round_id):
    return JsonResponse(buzzer.staff_desk(round_id, request.user))


@require_POST
@api_errors
def control(request, round_id):
    return JsonResponse(buzzer.control_window(round_id, request.user, json_body(request)))
