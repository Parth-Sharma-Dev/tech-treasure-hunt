from django.db import transaction
from django.http import JsonResponse
from django.views.decorators.http import require_GET, require_POST

from .api import api_errors, json_body
from .external_scores import HEADERS, commit_import, validate_import
from .models import AuditEvent, ExternalVoidProposal, ImportBatch
from .results import has_role, locked_round, require_result_view


@require_GET
@api_errors
@transaction.atomic
def desk(request, round_id):
    require_result_view(request.user)
    round = locked_round(round_id)
    batches = list(
        ImportBatch.objects.filter(round=round)
        .order_by("-pk")[:100]
        .values(
            "id",
            "maker_id",
            "schema_version",
            "reason",
            "preview",
            "dry_run_errors",
            "committed_at",
            "source_rows",
        )
    )
    from .external_scores import AuditEventRejected

    for batch in batches:
        if round.number == 5:
            from .buzzer_scores import rejected

            batch["rejected"] = rejected(ImportBatch(pk=batch["id"]))
        else:
            batch["rejected"] = AuditEventRejected(ImportBatch(pk=batch["id"]))
    proposals = list(
        ExternalVoidProposal.objects.filter(round=round)
        .order_by("-pk")
        .values("id", "maker_id", "question_id", "source_reference", "reason")
    )
    for proposal in proposals:
        proposal["reviewed"] = AuditEvent.objects.filter(
            action="external_question_void", after__response__reviewed_proposal_id=proposal["id"]
        ).exists()
    context = {}
    from .green_cards import is_green_cards

    if round.number == 5 and round.delivery_mode == "BUZZER":
        from .buzzer_scores import source_context

        context = source_context(round)
    return JsonResponse(
        {
            "actor_id": request.user.pk,
            **context,
            "can_prepare": has_role(request.user, "control_round", "adjudicate"),
            "can_review": has_role(request.user, "verify_evidence"),
            "round": {
                "id": round.pk,
                "number": round.number,
                "state": round.state,
                "title": round.title,
                "schema": round.rules_snapshot.get("rules", round.rules).get("score_schema", {}),
                "headers": ["team_name"]
                if is_green_cards(round)
                else HEADERS.get(round.number, []),
            },
            "batches": batches,
            "void_proposals": proposals,
        }
    )


@require_POST
@api_errors
def validate(request, round_id):
    return JsonResponse(validate_import(round_id, request.user, json_body(request)))


@require_POST
@api_errors
def commit(request, round_id, batch_id):
    data = json_body(request)
    data["batch_id"] = batch_id
    return JsonResponse(commit_import(round_id, request.user, data))


@require_POST
@api_errors
def void(request, round_id):
    from .external_voids import question_void

    return JsonResponse(question_void(round_id, request.user, json_body(request)))
