from django.db import DatabaseError, connection
from django.http import JsonResponse
from django.middleware.csrf import get_token
from django.views.decorators.http import require_GET


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
