from django.http import JsonResponse
from django.views.decorators.http import require_GET, require_POST

from .api import ApiProblem, api_errors, json_body
from .clock import database_now
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


@require_GET
@api_errors
def staff_rounds(request):
    from .models import Round
    from .results import require_result_view

    require_result_view(request.user)
    return JsonResponse(
        {
            "rounds": list(
                Round.objects.filter(number=3, delivery_mode="CODING")
                .order_by("-attempt_no")
                .values("id", "title", "attempt_no", "state", "is_demo")
            )
        }
    )


@require_GET
@api_errors
def staff_desk(request, round_id):
    from .coding_results import latest_grade
    from .models import (
        CodingJudgment,
        CodingJudgmentProposal,
        CodingSubmission,
        CodingWorkstation,
        Round,
        TeamSession,
    )
    from .results import has_role, require_result_view

    require_result_view(request.user)
    round = Round.objects.filter(pk=round_id).first()
    if round is None:
        raise ApiProblem("not_found", "Coding round not found.", 404)
    from .coding import native_round

    native_round(round)
    submissions = []
    for item in (
        CodingSubmission.objects.filter(round=round).select_related("team").order_by("team__code")
    ):
        grade = latest_grade(item)
        submissions.append(
            {
                "id": item.pk,
                "team_code": item.team.code,
                "kind": item.kind,
                "submitted_at": item.submitted_at.isoformat(),
                "supervisor_id": item.workstation_evidence.get("supervisor_id"),
                "score": str(grade.score) if grade else None,
            }
        )
    return JsonResponse(
        {
            "round_id": round.pk,
            "state": round.state,
            "actor_id": request.user.pk,
            "can_assign": has_role(request.user, "control_round"),
            "can_judge": has_role(request.user, "control_round", "adjudicate"),
            "can_review": has_role(request.user, "verify_evidence"),
            "submissions": submissions,
            "sessions": list(
                TeamSession.objects.filter(
                    team__is_demo=round.is_demo,
                    revoked_at__isnull=True,
                    expires_at__gt=database_now(),
                ).values("id", "team__code", "last_seen_at")
            ),
            "stations": list(
                CodingWorkstation.objects.filter(round=round).values(
                    "team__code", "label", "version", "session_id"
                )
            ),
            "proposals": [
                {
                    "id": p.pk,
                    "team_code": p.submission.team.code,
                    "maker_id": p.maker_id,
                    "reason": p.reason,
                    "payload": p.payload,
                    "reviewed": CodingJudgment.objects.filter(proposal=p).exists(),
                }
                for p in CodingJudgmentProposal.objects.filter(submission__round=round)
                .select_related("submission__team")
                .order_by("-pk")[:100]
            ],
        }
    )


@require_GET
@api_errors
def bundle(request, round_id, submission_id):
    from .coding import native_round, revision_payload, submission_payload
    from .models import CodingSubmission, Round
    from .results import require_result_view

    require_result_view(request.user)
    round = Round.objects.filter(pk=round_id).first()
    if round is None:
        raise ApiProblem("not_found", "Coding round not found.", 404)
    native_round(round)
    item = (
        CodingSubmission.objects.filter(pk=submission_id, round=round)
        .select_related("team")
        .first()
    )
    if item is None:
        raise ApiProblem("not_found", "Final bundle not found.", 404)
    from .models import CodingRevision

    return JsonResponse(
        {
            "submission": submission_payload(item),
            "supervisor_id": item.workstation_evidence.get("supervisor_id"),
            "team_code": item.team.code,
            "tasks": round.rules_snapshot["coding_tasks"],
            "responses": [
                revision_payload(rev)
                for rev in CodingRevision.objects.filter(
                    pk__in=[entry["revision_id"] for entry in item.manifest],
                    team=item.team,
                    round=round,
                )
            ],
        }
    )


@require_POST
@api_errors
def judgment(request, round_id):
    from .coding_results import approve_judgment, propose_judgment

    data = json_body(request)
    if data.get("action") == "propose":
        result = propose_judgment(round_id, request.user, data)
    elif data.get("action") == "approve":
        result = approve_judgment(round_id, request.user, data)
    else:
        raise ApiProblem("invalid_request", "Choose propose or approve lab judgment.")
    return JsonResponse({"request_id": request.request_id, **result})
