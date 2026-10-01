from django.db import DatabaseError, connection
from django.http import JsonResponse
from django.middleware.csrf import get_token
from django.views.csrf import csrf_failure as default_csrf_failure
from django.views.decorators.http import require_GET

from competition.api import ApiProblem, problem_response


def csrf_failure(request, reason=""):
    if request.path.startswith("/api/"):
        return problem_response(
            request, ApiProblem("csrf_failed", "Refresh the page and try again.", 403)
        )
    return default_csrf_failure(request, reason=reason)


@require_GET
def health(request):
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
            cursor.fetchone()
    except DatabaseError:
        # Connection strings, credentials and database exceptions stay private.
        return JsonResponse({"status": "unavailable", "request_id": request.request_id}, status=503)
    return JsonResponse({"status": "ok", "request_id": request.request_id})


@require_GET
def csrf(request):
    return JsonResponse({"csrf_token": get_token(request), "request_id": request.request_id})
