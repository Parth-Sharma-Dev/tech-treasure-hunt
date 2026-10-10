"""A faulty paper question is excluded for every team, preserving original credit."""

from django.db import transaction

from .api import ApiProblem
from .external_scores import intake_digest, require_external, voided_questions
from .models import ExternalQuestionVoid, ExternalVoidProposal
from .results import (
    audit_replay,
    locked_round,
    record_action,
    require_result_role,
    validate_request,
)
from .rules import require_staff_permission


@transaction.atomic
def question_void(round_id, actor, data):
    review = data.get("operation") == "review"
    if review:
        require_staff_permission(actor, "verify_evidence")
    else:
        require_result_role(actor)
    action_id, reason = validate_request(data)
    round = locked_round(round_id)
    fingerprint = {
        **data,
        "kind": "external_question_void",
        "round_id": round_id,
        "actor_id": actor.pk,
    }
    if replay := audit_replay(action_id, fingerprint):
        return replay
    require_external(round)
    from .wayground import is_wayground

    if is_wayground(round):
        raise ApiProblem(
            "unsupported_correction",
            "Correct Wayground scores using a reviewed replacement export.",
            409,
        )
    if round.number != 2 or round.state not in ["ENDED", "PROVISIONAL"]:
        raise ApiProblem(
            "invalid_transition",
            "Review global question voids after Round 2 ends and before finalization.",
            409,
        )
    if review:
        proposal = (
            ExternalVoidProposal.objects.filter(round=round, pk=data.get("proposal_id")).first()
            if type(data.get("proposal_id")) is int
            else None
        )
        if proposal is None:
            raise ApiProblem("not_found", "Void proposal not found.", 404)
        if proposal.maker_id == actor.pk:
            raise ApiProblem(
                "independent_reviewer", "A different reviewer must verify the faulty question.", 403
            )
        require_result_role(proposal.maker)
        from .models import AuditEvent

        if AuditEvent.objects.filter(
            action="external_question_void", after__response__reviewed_proposal_id=proposal.pk
        ).exists():
            raise ApiProblem(
                "invalid_transition", "This question proposal has already been reviewed.", 409
            )
        rejected = data.get("reject") is True
        if not rejected:
            if proposal.evidence_digest != intake_digest(round):
                raise ApiProblem(
                    "stale_evidence",
                    "Score evidence changed; prepare a new question void proposal.",
                    409,
                )
            if data.get("evidence_confirmed") is not True:
                raise ApiProblem(
                    "evidence_required",
                    "Confirm the faulty question and its removal for all teams.",
                )
            ExternalQuestionVoid.objects.create(proposal=proposal, verifier=actor)
            round.control_version += 1
            round.save(update_fields=["control_version"])
        response = {"reviewed_proposal_id": proposal.pk, "rejected": rejected}
    elif data.get("operation") == "propose":
        question = data.get("question_id")
        allowed = round.rules_snapshot["rules"]["score_schema"]["question_ids"]
        if (
            not isinstance(question, str)
            or question not in allowed
            or question in voided_questions(round)
            or len(voided_questions(round)) >= len(allowed) - 1
        ):
            raise ApiProblem(
                "invalid_question",
                "Select a released nonvoid question; the paper must retain a positive maximum.",
            )
        ref = data.get("source_reference")
        if not isinstance(ref, str) or not ref.strip() or len(ref) > 200:
            raise ApiProblem(
                "evidence_required", "Supply a private faulty-question evidence reference."
            )
        proposal = ExternalVoidProposal.objects.create(
            round=round,
            maker=actor,
            question_id=question,
            source_reference=ref,
            reason=reason,
            evidence_digest=intake_digest(round),
        )
        response = {"proposal_id": proposal.pk}
    else:
        raise ApiProblem("invalid_request", "Choose propose or review.")
    record_action(action_id, actor, "external_question_void", reason, fingerprint, response)
    return response
