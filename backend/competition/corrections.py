"""Two-person Round 1 corrections without rewriting original decisions or receipts."""

import hmac
import re
from datetime import timedelta

from django.db import transaction
from django.views.decorators.debug import sensitive_variables

from .answers import answer_digest
from .api import ApiProblem
from .clock import close_phase, database_now
from .models import (
    Completion,
    Incident,
    Mission,
    MissionResolution,
    ResolutionProposal,
    ResultSnapshot,
    Round,
    SubmissionDecision,
    Team,
)
from .results import (
    audit_replay,
    build_preview,
    digest,
    has_role,
    latest_snapshot,
    record_action,
    require_result_role,
    validate_request,
)
from .rules import require_staff_permission


def correction_lock(round_id):
    # Lock all cohort rounds in a consistent order before teams: post-final changes
    # may need to pause dependent play as well as change the source round.
    identity = Round.objects.filter(pk=round_id).first()
    if identity is None:
        raise ApiProblem("not_found", "Round not found.", 404)
    rounds = list(Round.objects.select_for_update().filter(is_demo=identity.is_demo).order_by("pk"))
    round = next(item for item in rounds if item.pk == round_id)
    list(Team.objects.select_for_update().filter(is_demo=round.is_demo).order_by("pk"))
    if round.number != 1 or round.delivery_mode != "ONLINE_HUNT":
        raise ApiProblem("unsupported_round", "Corrections here support Round 1 only.", 409)
    return round, rounds


def evidence(round):
    return digest(
        {
            "preview": build_preview(round, database_now())["evidence_digest"],
            "keys": list(
                Mission.objects.filter(round=round).order_by("pk").values("id", "answer_verifiers")
            ),
        }
    )


def evidence_refs(data):
    refs = data.get("evidence_refs")
    if (
        not isinstance(refs, list)
        or not refs
        or len(refs) > 100
        or any(not isinstance(ref, str) or not ref.strip() or len(ref) > 500 for ref in refs)
    ):
        raise ApiProblem("evidence_required", "Supply private supporting evidence references.")
    return refs


@transaction.atomic
@sensitive_variables("answer", "data")
def propose_correction(round_id, actor, data):
    require_result_role(actor)
    action_id, reason = validate_request(data)
    round, _ = correction_lock(round_id)
    kind = data.get("correction_type")
    if kind not in ["ALTERNATE", "VOID"]:
        raise ApiProblem("invalid_request", "Choose an alternate answer or mission void.")
    mission = (
        Mission.objects.filter(pk=data.get("mission_id"), round=round, is_practice=False).first()
        if type(data.get("mission_id")) is int
        else None
    )
    if mission is None:
        raise ApiProblem("not_found", "Competitive mission not found.", 404)
    payload = {"evidence_refs": evidence_refs(data), "public_summary": data.get("public_summary")}
    if (
        not isinstance(payload["public_summary"], str)
        or not payload["public_summary"].strip()
        or len(payload["public_summary"]) > 2000
    ):
        raise ApiProblem("invalid_request", "Supply a participant-facing correction summary.")
    if kind == "ALTERNATE":
        answer = data.get("answer")
        if not isinstance(answer, str) or re.fullmatch(r"[0-9]{4}", answer) is None:
            raise ApiProblem("invalid_format", "Supply exactly four ASCII digits.")
        versions = {item["version"] for item in mission.answer_verifiers}
        versions.update(
            SubmissionDecision.objects.filter(mission=mission, outcome="incorrect").values_list(
                "answer_key_version", flat=True
            )
        )
        payload["verifiers"] = [
            {"version": version, "digest": answer_digest(mission.pk, version, answer)}
            for version in sorted(versions)
            if version
        ]
    fingerprint = {
        "kind": "correction_propose",
        "round_id": round_id,
        "actor_id": actor.pk,
        "mission_id": mission.pk,
        "correction_type": kind,
        "reason": reason,
        "payload": payload,
        "expected_version": data.get("expected_version"),
    }
    if original := audit_replay(action_id, fingerprint):
        return original
    if round.state in ["DRAFT", "READY", "LOBBY"] or mission.is_void:
        raise ApiProblem(
            "invalid_transition",
            "Correct a released, non-void competitive mission after play starts.",
            409,
        )
    if (
        type(data.get("expected_version")) is not int
        or data["expected_version"] != round.control_version
    ):
        raise ApiProblem(
            "stale_evidence", "Round changed. Refresh before proposing a correction.", 409
        )
    incident = Incident.objects.create(
        round=round,
        category="SCORING",
        affected_scope={"summary": reason, "mission_id": mission.pk},
        opened_at=database_now(),
        owner=actor,
        material=True,
        evidence_references=payload["evidence_refs"],
    )
    proposal = ResolutionProposal.objects.create(
        round=round,
        mission=mission,
        correction_type=kind,
        payload=payload,
        expected_version=round.control_version,
        evidence_digest=evidence(round),
        reason=reason,
        maker=actor,
        incident=incident,
    )
    response = {"correction_proposal_id": proposal.pk, "incident_id": incident.pk}
    record_action(action_id, actor, "propose_correction", reason, fingerprint, response)
    return response


@transaction.atomic
def approve_correction(round_id, actor, data):
    require_staff_permission(actor, "verify_evidence")
    action_id, reason = validate_request(data)
    round, cohort_rounds = correction_lock(round_id)
    fingerprint = {**data, "kind": "correction_approve", "round_id": round_id, "actor_id": actor.pk}
    if original := audit_replay(action_id, fingerprint):
        return original
    if type(data.get("proposal_id")) is not int:
        raise ApiProblem("invalid_request", "Supply a correction proposal ID.")
    proposal = (
        ResolutionProposal.objects.select_related("mission", "incident", "maker")
        .filter(pk=data["proposal_id"], round=round)
        .first()
    )
    if proposal is None:
        raise ApiProblem("not_found", "Correction proposal not found.", 404)
    if actor.pk == proposal.maker_id:
        raise ApiProblem(
            "independent_reviewer", "A different verifier must approve the correction.", 403
        )
    if not has_role(proposal.maker, "control_round", "adjudicate"):
        raise ApiProblem("maker_unauthorized", "The correction maker is no longer authorized.", 409)
    if data.get("evidence_confirmed") is not True:
        raise ApiProblem(
            "evidence_required", "Confirm independent review of the correction evidence."
        )
    if MissionResolution.objects.filter(proposal=proposal).exists():
        raise ApiProblem("already_applied", "This correction has already been applied.", 409)
    if data.get("reject") is True:
        resolution = MissionResolution.objects.create(
            mission=proposal.mission,
            proposal=proposal,
            correction_type="REJECTED",
            reason=reason,
            maker=proposal.maker,
            approver=actor,
            incident=proposal.incident,
            evidence_references=proposal.payload["evidence_refs"],
        )
        proposal.incident.closed_at = database_now()
        proposal.incident.decision = reason
        proposal.incident.save(update_fields=["closed_at", "decision"])
        round.control_version += 1
        round.save(update_fields=["control_version"])
        response = {"resolution_id": resolution.pk, "rejected": True, "state": round.state}
        record_action(action_id, actor, "reject_correction", reason, fingerprint, response)
        return response
    if proposal.expected_version != round.control_version or proposal.evidence_digest != evidence(
        round
    ):
        raise ApiProblem(
            "stale_evidence",
            "Evidence changed. Prepare and independently review a fresh proposal.",
            409,
        )
    was_final = round.state == "FINALIZED"
    dependent = [
        item
        for item in cohort_rounds
        if item.number > 1 and item.state not in ["DRAFT", "READY", "LOBBY"]
    ]
    if was_final:
        require_staff_permission(actor, "publish_results")
        if data.get("supersession_confirmed") is not True:
            raise ApiProblem(
                "supersession_required",
                "Confirm that final results will be superseded by provisional results.",
                409,
            )
        if dependent and data.get("progression_impact_confirmed") is not True:
            raise ApiProblem(
                "progression_impact",
                "Confirm suspension and incident review for dependent rounds already started.",
                409,
            )
    mission = proposal.mission
    source_ids = []
    candidates = []
    if proposal.correction_type == "ALTERNATE":
        candidates = [
            item
            for item in SubmissionDecision.objects.filter(
                mission=mission, outcome="incorrect"
            ).order_by("admitted_at", "pk")
            if any(
                v["version"] == item.answer_key_version
                and hmac.compare_digest(v["digest"], item.answer_hmac)
                for v in proposal.payload["verifiers"]
            )
        ]
        source_ids = [str(item.pk) for item in candidates]
    resolution = MissionResolution.objects.create(
        mission=mission,
        correction_type=proposal.correction_type,
        affected_scope={"public_summary": proposal.payload["public_summary"]},
        evidence_references=proposal.payload["evidence_refs"],
        source_decisions=source_ids,
        reason=proposal.reason,
        maker=proposal.maker,
        approver=actor,
        incident=proposal.incident,
        proposal=proposal,
    )
    if proposal.correction_type == "VOID":
        Mission.objects.filter(pk=mission.pk).update(is_void=True)
    else:
        keys = list(mission.answer_verifiers)
        for key in proposal.payload["verifiers"]:
            if key not in keys:
                keys.append(key)
        Mission.objects.filter(pk=mission.pk).update(answer_verifiers=keys)
        for decision in candidates:
            current = Completion.objects.filter(team=decision.team, mission=mission).first()
            if current is None or decision.active_elapsed_ms < current.effective_active_ms:
                values = {
                    "source_decision": None,
                    "source_resolution": resolution,
                    "effective_at": decision.admitted_at,
                    "effective_active_ms": decision.active_elapsed_ms,
                    "revision": current.revision + 1 if current else 1,
                }
                Completion.objects.update_or_create(
                    team=decision.team, mission=mission, defaults=values
                )
    now = database_now()
    proposal.incident.closed_at = now
    proposal.incident.decision = reason
    proposal.incident.save(update_fields=["closed_at", "decision"])
    round.control_version += 1
    if was_final:
        round.state = "PROVISIONAL"
    round.save(update_fields=["control_version", "state"])
    if was_final:
        previous = latest_snapshot(round)
        preview = build_preview(round, now)
        ResultSnapshot.objects.create(
            round=round,
            revision=previous.revision + 1,
            status="PROVISIONAL",
            ranked_entries=preview["entries"],
            qualifier_codes=[],
            cut_count=preview["cut_count"],
            rules_digest=round.rules_digest,
            evidence_digest=preview["evidence_digest"],
            maker=proposal.maker,
            approver=actor,
            published_at=now,
            supersedes=previous,
            appeal_deadline=now
            + timedelta(minutes=round.rules_snapshot["rules"]["appeal_minutes"]),
            metadata={
                "publication_reason": proposal.payload["public_summary"],
                "review_reason": reason,
                "tie_reason": "",
                "open_material_incidents": preview["open_material_incidents"],
                "resolution_id": resolution.pk,
            },
        )
        for item in dependent:
            if item.state == "LIVE":
                close_phase(item, now, actor, "Source qualification superseded")
                item.state = "FROZEN"
                item.phase_started_at = now
                item.control_version += 1
                item.save()
            Incident.objects.create(
                round=item,
                category="QUALIFICATION_IMPACT",
                owner=proposal.maker,
                opened_at=now,
                material=True,
                affected_scope={
                    "summary": "Round 1 qualification changed; review dependent progression.",
                    "source_resolution_id": resolution.pk,
                },
                evidence_references=proposal.payload["evidence_refs"],
            )
    response = {
        "resolution_id": resolution.pk,
        "reclassified_decisions": len(source_ids),
        "state": round.state,
        "dependent_rounds": [item.pk for item in dependent] if was_final else [],
    }
    record_action(action_id, actor, "approve_correction", reason, fingerprint, response)
    return response
