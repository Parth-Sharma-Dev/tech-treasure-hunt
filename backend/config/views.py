from django.conf import settings
from django.db import DatabaseError, connection
from django.http import FileResponse, Http404, JsonResponse
from django.middleware.csrf import get_token
from django.views.csrf import csrf_failure as default_csrf_failure
from django.views.decorators.http import require_GET, require_safe

from competition.api import ApiProblem, problem_response


@require_safe
def frontend(request):
    """Return the public React shell only for explicitly registered browser routes."""
    try:
        response = FileResponse(
            (settings.FRONTEND_DIST_DIR / "index.html").open("rb"), content_type="text/html"
        )
    except FileNotFoundError:
        raise Http404("The frontend has not been deployed.") from None
    response["Cache-Control"] = "no-store"
    return response


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
