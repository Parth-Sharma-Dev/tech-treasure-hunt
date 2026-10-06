from uuid import uuid4

from django.utils import timezone


class RequestIdMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        # Generate locally rather than trusting arbitrary client header values.
        request.request_id = str(uuid4())
        request.ingress_at = timezone.now()
        response = self.get_response(request)
        response["X-Request-ID"] = request.request_id
        if request.path.startswith("/api/"):
            response["Cache-Control"] = "no-store"
        return response
