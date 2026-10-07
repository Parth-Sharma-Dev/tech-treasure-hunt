from django.db import transaction
from django.http import JsonResponse
from django.views.decorators.http import require_GET, require_POST

from .api import ApiProblem, api_errors, json_body
from .clock import database_now
from .corrections import evidence as correction_evidence
from .models import (
    Incident,
    Mission,
    MissionResolution,
    ResolutionProposal,
    ResultProposal,
    ResultSnapshot,
    Round,
)
from .results import (
    approve_result,
    build_preview,
    has_role,
    locked_round,
    manage_incident,
    propose_result,
    require_result_view,
)
from .sessions import require_team


def public_snapshot(snapshot):
    return {
        "id": snapshot.pk,
        "revision": snapshot.revision,
        "status": snapshot.status,
        "entries": snapshot.ranked_entries,
        "qualifier_codes": snapshot.qualifier_codes,
        "cut_count": snapshot.cut_count,
        "rules_digest": snapshot.rules_digest,
        "evidence_digest": snapshot.evidence_digest,
        "metadata": snapshot.metadata,
        "published_at": snapshot.published_at.isoformat(),
        "appeal_deadline": snapshot.appeal_deadline.isoformat()
        if snapshot.appeal_deadline
        else None,
        "supersedes": snapshot.supersedes_id,
    }


@require_GET
@api_errors
def published_results(request, round_id):
    team = require_team(request, allow_inactive=True)
    round = Round.objects.filter(pk=round_id, is_demo=team.is_demo).first()
    if round is None:
        raise ApiProblem("not_found", "Round not found.", 404)
    history = list(ResultSnapshot.objects.filter(round=round).order_by("-revision"))
    current = (
        Round.objects.filter(number=round.number, is_demo=round.is_demo)
        .order_by("-attempt_no")
        .first()
    )
    return JsonResponse(
        {
            "request_id": request.request_id,
            "round_id": round.pk,
            "title": round.title,
            "number": round.number,
            "attempt_no": round.attempt_no,
            "current_attempt": current.pk == round.pk,
            "own_team_code": team.code,
            "server_time": database_now().isoformat(),
            "snapshot": public_snapshot(history[0]) if history else None,
            "history": [public_snapshot(snapshot) for snapshot in history],
        }
    )


@require_GET
@api_errors
def staff_result_rounds(request):
    require_result_view(request.user)
    return JsonResponse(
        {
            "request_id": request.request_id,
            "rounds": list(
                Round.objects.order_by("number", "-attempt_no").values(
                    "id", "number", "attempt_no", "title", "state", "is_demo"
                )
            ),
        }
    )


@require_GET
@api_errors
@transaction.atomic
def staff_preview(request, round_id):
    require_result_view(request.user)
    round = locked_round(round_id)
    preview = build_preview(round, database_now())
    correction_digest = correction_evidence(round)
    proposals = []
    for proposal in (
        ResultProposal.objects.filter(round=round).select_related("maker").order_by("-pk")[:30]
    ):
        snapshot = ResultSnapshot.objects.filter(proposal=proposal).first()
        proposals.append(
            {
                "id": proposal.pk,
                "status": proposal.target_status,
                "maker_id": proposal.maker_id,
                "maker_name": proposal.maker.get_username(),
                "reason": proposal.reason,
                "payload": proposal.payload,
                "publication_id": snapshot.pk if snapshot else None,
                "stale": proposal.expected_version != round.control_version
                or proposal.evidence_digest != preview["evidence_digest"],
            }
        )
    return JsonResponse(
        {
            "request_id": request.request_id,
            **preview,
            "actor_id": request.user.pk,
            "can_propose": has_role(request.user, "control_round", "adjudicate"),
            "can_approve": has_role(request.user, "publish_results")
            and has_role(request.user, "verify_evidence"),
            "can_close_incident": has_role(request.user, "verify_evidence"),
            "can_correct": round.number == 1
            and has_role(request.user, "control_round", "adjudicate"),
            "correction_version_digest": correction_digest,
            "missions": list(
                Mission.objects.filter(round=round, is_practice=False)
                .order_by("pk")
                .values("id", "public_id", "is_void")
            ),
            "corrections": [
                {
                    "id": item.pk,
                    "mission_id": item.mission_id,
                    "correction_type": item.correction_type,
                    "maker_id": item.maker_id,
                    "reason": item.reason,
                    "payload": item.payload,
                    "resolution_id": MissionResolution.objects.filter(proposal=item)
                    .values_list("pk", flat=True)
                    .first(),
                    "stale": item.expected_version != round.control_version
                    or item.evidence_digest != correction_digest,
                }
                for item in ResolutionProposal.objects.filter(round=round).order_by("-pk")[:30]
            ],
            "proposals": proposals,
            "incidents": list(
                Incident.objects.filter(round=round)
                .order_by("-pk")
                .values(
                    "id",
                    "category",
                    "affected_scope",
                    "material",
                    "owner_id",
                    "opened_at",
                    "closed_at",
                    "decision",
                    "evidence_references",
                )
            ),
            "history": [
                public_snapshot(item)
                for item in ResultSnapshot.objects.filter(round=round).order_by("-revision")
            ],
        }
    )


@require_POST
@api_errors
def publish(request, round_id):
    data = json_body(request)
    action = data.get("action")
    if action == "propose":
        result = propose_result(round_id, request.user, data)
    elif action == "approve":
        result = approve_result(round_id, request.user, data)
    else:
        raise ApiProblem("invalid_request", "Choose propose or approve publication.")
    return JsonResponse({"request_id": request.request_id, **result})


@require_POST
@api_errors
def incident(request, round_id):
    result = manage_incident(round_id, request.user, json_body(request))
    return JsonResponse({"request_id": request.request_id, **result})


@require_POST
@api_errors
def resolutions(request, round_id):
    from .corrections import approve_correction, propose_correction

    data = json_body(request)
    if data.get("action") == "propose":
        result = propose_correction(round_id, request.user, data)
    elif data.get("action") == "approve":
        result = approve_correction(round_id, request.user, data)
    else:
        raise ApiProblem("invalid_request", "Choose propose or approve correction.")
    return JsonResponse({"request_id": request.request_id, **result})


@require_POST
@api_errors
def paper_action(request, round_id):
    from .paper import approve_paper, end_paper, propose_paper

    data = json_body(request)
    handlers = {"propose": propose_paper, "approve": approve_paper, "end": end_paper}
    action = data.get("action")
    if not isinstance(action, str) or action not in handlers:
        raise ApiProblem("invalid_request", "Choose propose, approve or end paper play.")
    result = handlers[action](round_id, request.user, data)
    return JsonResponse({"request_id": request.request_id, **result})
