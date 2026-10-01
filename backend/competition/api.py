import json
from functools import wraps

from django.core.exceptions import PermissionDenied, RequestDataTooBig
from django.db import DatabaseError
from django.http import JsonResponse


class ApiProblem(Exception):
    def __init__(self, code, message, status=400, retry_after=None):
        super().__init__(message)
        self.code = code
        self.status = status
        self.retry_after = retry_after


def problem_response(request, problem):
    response = JsonResponse(
        {
            "request_id": request.request_id,
            "error": {"code": problem.code, "message": str(problem)},
        },
        status=problem.status,
    )
    if problem.retry_after is not None:
        response["Retry-After"] = str(problem.retry_after)
    return response


def api_errors(view):
    @wraps(view)
    def wrapped(request, *args, **kwargs):
        try:
            return view(request, *args, **kwargs)
        except ApiProblem as problem:
            return problem_response(request, problem)
        except PermissionDenied:
            return problem_response(
                request, ApiProblem("forbidden", "Access is not permitted.", 403)
            )
        except (RequestDataTooBig, UnicodeDecodeError, json.JSONDecodeError):
            return problem_response(
                request, ApiProblem("invalid_request", "Send a valid JSON object.")
            )
        except DatabaseError:
            return problem_response(
                request,
                ApiProblem("service_unavailable", "Connection unavailable. Please try again.", 503),
            )

    return wrapped


def json_body(request):
    if request.content_type != "application/json":
        raise ApiProblem("invalid_request", "Send a JSON request.", 415)
    data = json.loads(request.body)
    if not isinstance(data, dict):
        raise ApiProblem("invalid_request", "Send a JSON object.")
    return data
