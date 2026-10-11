from uuid import uuid4

from django.conf import settings
from django.utils import timezone


class StaffMfaMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if settings.STAFF_MFA_REQUIRED and (
            request.path == "/api/staff" or request.path.startswith("/api/staff/")
        ):
            from competition.api import ApiProblem, problem_response
            from competition.mfa import staff_mfa_verified

            if not request.user.is_authenticated:
                return problem_response(
                    request,
                    ApiProblem(
                        "staff_login_required",
                        "Sign in with your staff password and authentication code.",
                        403,
                    ),
                )
            if request.user.is_staff and not staff_mfa_verified(request):
                return problem_response(
                    request,
                    ApiProblem(
                        "staff_mfa_required",
                        "Staff MFA sign-in is required before continuing.",
                        403,
                    ),
                )
        return self.get_response(request)


class AllowedHostMiddleware:
    """Validate hosts even on read-only endpoints and static-file requests."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        request.get_host()
        return self.get_response(request)


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
