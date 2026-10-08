from django.http import JsonResponse
from django.views.decorators.http import require_GET, require_POST

from .api import ApiProblem, api_errors, json_body
from .models import AuditEvent, RosterProposal, Team
from .results import has_role
from .roster import FIELDS, credentials, propose_roster, review_roster


@require_GET
@api_errors
def desk(request):
    if not has_role(request.user, "control_round", "verify_evidence"):
        raise ApiProblem("permission_denied", "Roster staff access is required.", 403)
    proposals = list(
        RosterProposal.objects.order_by("-pk")[:100].values("id", "maker_id", "payload", "reason")
    )
    for item in proposals:
        item["reviewed"] = AuditEvent.objects.filter(
            action="review_roster", after__response__proposal_id=item["id"]
        ).exists()
    return JsonResponse(
        {
            "actor_id": request.user.pk,
            "can_prepare": has_role(request.user, "control_round"),
            "can_review": has_role(request.user, "verify_evidence"),
            "headers": FIELDS,
            "teams": list(
                Team.objects.order_by("is_demo", "code").values(
                    "id", *FIELDS, "is_demo", "session_version"
                )
            ),
            "proposals": proposals,
        }
    )


@require_POST
@api_errors
def change(request):
    data = json_body(request)
    if data.get("operation") == "propose":
        return JsonResponse(propose_roster(request.user, data))
    if data.get("operation") == "review":
        return JsonResponse(review_roster(request.user, data))
    raise ApiProblem("invalid_request", "Choose propose or review.")


@require_POST
@api_errors
def issue_credentials(request, team_id):
    return JsonResponse(credentials(request.user, team_id, json_body(request)))
