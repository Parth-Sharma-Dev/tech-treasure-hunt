"""Reviewed, immutable Round 1 publication; live previews never reach participants."""

import hashlib
import json
import uuid
from datetime import timedelta

from django.core.exceptions import PermissionDenied, ValidationError
from django.core.signing import BadSignature, Signer
from django.db import IntegrityError, transaction

from .api import ApiProblem
from .clock import database_now, milliseconds
from .models import (
    AuditEvent,
    Completion,
    Incident,
    Mission,
    MissionResolution,
    PaperProposal,
    PaperSlip,
    PaperWindow,
    ResultProposal,
    ResultSnapshot,
    Round,
    RoundPhase,
    ScoreRevision,
    SubmissionDecision,
    Team,
)
from .rules import require_staff_permission, snapshot_digest


def has_role(actor, *roles):
    return (
        actor.is_active
        and actor.is_staff
        and any(actor.has_perm(f"competition.{role}") for role in roles)
    )


def require_result_role(actor, review=False):
    allowed = ("publish_results",) if review else ("control_round", "adjudicate")
    if not has_role(actor, *allowed):
        raise PermissionDenied("An authorized results account is required.")


def require_result_view(actor):
    if not has_role(actor, "control_round", "adjudicate", "verify_evidence", "publish_results"):
        raise PermissionDenied("An authorized results account is required.")


def digest(value):
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode()
    ).hexdigest()


def latest_snapshot(round):
    return ResultSnapshot.objects.filter(round=round).order_by("-revision").first()


def locked_round(round_id):
    round = Round.objects.select_for_update().filter(pk=round_id).first()
    if round is None:
        raise ApiProblem("not_found", "Round not found.", 404)
    # Roster/status changes use the same ordering as gameplay and corrections.
    list(Team.objects.select_for_update().filter(is_demo=round.is_demo).order_by("pk"))
    return round


def build_preview(round, now):
    teams = list(Team.objects.filter(is_demo=round.is_demo).order_by("code"))
    missions = list(Mission.objects.filter(round=round, is_practice=False).order_by("pk"))
    completions = list(
        Completion.objects.filter(mission__round=round)
        .select_related("mission", "team", "source_decision", "source_resolution")
        .order_by("pk")
    )
    phases = list(RoundPhase.objects.filter(round=round).order_by("started_at", "pk"))
    decisions = list(SubmissionDecision.objects.filter(round=round).order_by("pk"))
    incidents = list(Incident.objects.filter(round=round).order_by("pk"))
    gaps = []
    if round.number != 1 or round.delivery_mode != Round.Delivery.ONLINE_HUNT:
        gaps.append("Only online Round 1 completion rankings are supported in this workflow.")
    window = PaperWindow.objects.filter(round=round).first()
    slips = list(PaperSlip.objects.filter(round=round).order_by("pk"))
    if round.play_mode == Round.PlayMode.PAPER and (
        window is None
        or window.recorder_id == window.verifier_id
        or not window.clock_evidence
        or not window.writer_isolation_evidence
    ):
        gaps.append("Paper play needs independently verified clock and writer-isolation evidence.")
    if ScoreRevision.objects.filter(round=round).exists():
        gaps.append("Penalty or external-score evidence needs its separate adjudication workflow.")
    if round.state not in {"ENDED", "PROVISIONAL", "FINALIZED"}:
        gaps.append("End and persist the round before publishing results.")
    if not round.rules_digest or not round.rules_snapshot:
        gaps.append("The approved rules snapshot is missing.")
    elif snapshot_digest(round.rules_snapshot) != round.rules_digest:
        gaps.append("The approved rules snapshot does not match its frozen digest.")
    if round.live_started_at or round.phase_started_at or round.deadline_at:
        gaps.append("An unclosed clock interval needs reconciliation.")
    if not phases or not any(phase.phase_type == "LIVE" for phase in phases):
        gaps.append("Completed live clock evidence is missing.")
    for previous, current in zip(phases, phases[1:], strict=False):
        if previous.ended_at != current.started_at:
            gaps.append("Round phase coverage has a gap or overlap.")
            break
    live_ms = sum(
        milliseconds(phase.ended_at - phase.started_at)
        for phase in phases
        if phase.phase_type == "LIVE"
    )
    if live_ms != round.accumulated_active_ms:
        gaps.append("Persisted active time does not match the recorded live intervals.")
    by_team = {team.pk: [] for team in teams}
    for completion in completions:
        try:
            completion.clean()
        except ValidationError:
            gaps.append("A completion has inconsistent source or mission evidence.")
        if completion.team_id not in by_team or completion.mission.is_practice:
            gaps.append("A completion belongs to the wrong cohort or to practice.")
            continue
        source = completion.source_decision
        if source:
            keys = completion.mission.answer_verifiers
            if not any(
                item.get("version") == source.answer_key_version
                and item.get("digest") == source.answer_hmac
                for item in keys
            ):
                gaps.append("An accepted decision has missing or inconsistent answer-key evidence.")
            try:
                receipt = Signer(salt="competition.accepted-receipt.v1").unsign_object(
                    source.response_snapshot["receipt"]
                )
                if not isinstance(receipt, dict) or (
                    receipt.get("decision_id") != str(source.pk)
                    or receipt.get("team_code") != completion.team.code
                    or receipt.get("active_elapsed_ms") != source.active_elapsed_ms
                    or receipt.get("outcome") != "accepted"
                ):
                    gaps.append("An accepted receipt does not match its decision evidence.")
            except (BadSignature, ValueError, TypeError, KeyError):
                gaps.append("An accepted decision's signed receipt is missing or invalid.")
            covered = [
                phase
                for phase in phases
                if phase.phase_type == "LIVE"
                and phase.play_mode == "ONLINE"
                and phase.started_at <= source.admitted_at <= phase.ended_at
            ]
            expected_elapsed = None
            if covered:
                phase = covered[0]
                expected_elapsed = sum(
                    milliseconds(item.ended_at - item.started_at)
                    for item in phases
                    if item.phase_type == "LIVE" and item.ended_at < phase.started_at
                )
                # A preceding LIVE interval may end exactly where a zero-length freeze starts.
                expected_elapsed += sum(
                    milliseconds(item.ended_at - item.started_at)
                    for item in phases
                    if item.phase_type == "LIVE"
                    and item.pk != phase.pk
                    and item.ended_at == phase.started_at
                )
                expected_elapsed += milliseconds(source.admitted_at - phase.started_at)
            if (
                source.round_id != round.pk
                or source.rules_version != round.rules_version
                or completion.effective_at != source.admitted_at
                or completion.effective_active_ms != source.active_elapsed_ms
                or source.active_elapsed_ms != expected_elapsed
            ):
                gaps.append("A completion's admission or active-time evidence is inconsistent.")
        else:
            resolution = completion.source_resolution
            if resolution and (
                resolution.incident.round_id != round.pk
                or resolution.maker_id == resolution.approver_id
            ):
                gaps.append("A resolution requires matching round evidence and independent review.")
            if resolution and resolution.correction_type == "ALTERNATE":
                originals = [
                    item
                    for item in decisions
                    if str(item.pk) in resolution.source_decisions
                    and item.team_id == completion.team_id
                    and item.mission_id == completion.mission_id
                    and item.outcome == "incorrect"
                    and item.admitted_at == completion.effective_at
                    and item.active_elapsed_ms == completion.effective_active_ms
                ]
                if not originals:
                    originals = [
                        item
                        for item in slips
                        if f"paper:{item.pk}" in resolution.source_decisions
                        and item.team_id == completion.team_id
                        and item.mission_id == completion.mission_id
                        and item.outcome == "incorrect"
                        and item.evaluated_at == completion.effective_at
                        and item.active_elapsed_ms == completion.effective_active_ms
                    ]
                if not originals:
                    gaps.append(
                        "A corrected completion is missing its original evaluated answer evidence."
                    )
                elif resolution.proposal is None or not any(
                    verifier.get("version") == original.answer_key_version
                    and verifier.get("digest") == original.answer_hmac
                    for original in originals
                    for verifier in resolution.proposal.payload.get("verifiers", [])
                ):
                    gaps.append(
                        "A corrected answer does not match its reviewed alternate-answer evidence."
                    )
            if resolution and resolution.correction_type == "PAPER_ACCEPTED":
                slip = next(
                    (
                        item
                        for item in slips
                        if item.pk == resolution.affected_scope.get("paper_slip_id")
                    ),
                    None,
                )
                if (
                    slip is None
                    or slip.outcome != "accepted"
                    or slip.team_id != completion.team_id
                    or slip.mission_id != completion.mission_id
                    or slip.evaluated_at != completion.effective_at
                    or slip.active_elapsed_ms != completion.effective_active_ms
                ):
                    gaps.append("A paper completion does not match its accepted numbered slip.")
        if completion.effective_active_ms > round.accumulated_active_ms:
            gaps.append("A completion falls outside the recorded active budget.")
        if not completion.mission.is_void:
            by_team[completion.team_id].append(completion)
    projected = {(item.team_id, item.mission_id) for item in completions}
    if any(
        item.outcome == "accepted" and (item.team_id, item.mission_id) not in projected
        for item in decisions
    ):
        gaps.append("An accepted decision is missing its effective completion projection.")
    for slip in slips:
        if (
            window is None
            or slip.maker_id == slip.verifier_id
            or window.assigned_desks.get(slip.team.code) != slip.desk
            or slip.active_elapsed_ms
            != window.active_offset_ms + milliseconds(slip.evaluated_at - window.official_start)
            or not window.official_start <= slip.evaluated_at <= window.official_end
            or slip.active_elapsed_ms > round.accumulated_active_ms
        ):
            gaps.append("A paper slip has inconsistent desk, timing or review evidence.")
        if slip.outcome == "accepted" and (slip.team_id, slip.mission_id) not in projected:
            gaps.append("An accepted paper slip is missing its completion projection.")
        if (
            slip.outcome == "accepted"
            and {"version": slip.answer_key_version, "digest": slip.answer_hmac}
            not in slip.mission.answer_verifiers
        ):
            gaps.append("An accepted paper slip does not match a verified answer key.")
        if round.state in ["ENDED", "PROVISIONAL", "FINALIZED"] and not any(
            phase.phase_type == "LIVE"
            and phase.play_mode == "PAPER"
            and phase.started_at <= slip.evaluated_at <= phase.ended_at
            for phase in phases
        ):
            gaps.append("A paper slip falls outside the completed official paper interval.")
    if window and (
        window.active_offset_ms
        != sum(
            milliseconds(phase.ended_at - phase.started_at)
            for phase in phases
            if phase.phase_type == "LIVE" and phase.play_mode == "ONLINE"
        )
        or window.official_end
        != window.official_start + timedelta(milliseconds=window.remaining_budget_ms)
    ):
        gaps.append(
            "Paper clock offset or official duration differs from the reviewed interval evidence."
        )
    maximum = sum(mission.available and not mission.is_void for mission in missions)
    entries = []
    for team in teams:
        counted = by_team[team.pk]
        entries.append(
            {
                "team_code": team.code,
                "team_name": team.name,
                "team_status": team.status,
                "eligible": team.status == "ACTIVE",
                "score": len(counted),
                "max_score": maximum,
                "tie_time_ms": max((item.effective_active_ms for item in counted), default=None),
            }
        )
    entries.sort(
        key=lambda entry: (
            not entry["eligible"],
            -entry["score"],
            entry["tie_time_ms"] if entry["tie_time_ms"] is not None else 0,
            entry["team_code"],
        )
    )
    eligible = [entry for entry in entries if entry["eligible"]]
    previous_metric, rank = None, 0
    for position, entry in enumerate(eligible, 1):
        metric = (entry["score"], entry["tie_time_ms"])
        if metric != previous_metric:
            rank = position
        entry["rank"] = rank
        previous_metric = metric
    for entry in entries:
        if not entry["eligible"]:
            entry["rank"] = None
    cut = round.rules_snapshot.get("advancement_count")
    cutoff_tie = []
    config_errors = []
    if type(cut) is not int or cut <= 0:
        config_errors.append("The approved advancement count is missing.")
    elif (
        len(eligible) < cut
        and round.rules_snapshot.get("rules", {}).get("short_roster_policy")
        != "advance_all_eligible"
    ):
        config_errors.append("The short roster needs the approved advance-all-eligible policy.")
    elif 0 < cut < len(eligible):
        boundary = eligible[cut - 1]
        if (boundary["score"], boundary["tie_time_ms"]) == (
            eligible[cut]["score"],
            eligible[cut]["tie_time_ms"],
        ):
            cutoff_tie = [
                entry["team_code"]
                for entry in eligible
                if (entry["score"], entry["tie_time_ms"])
                == (boundary["score"], boundary["tie_time_ms"])
            ]
    open_incidents = sum(incident.material and incident.closed_at is None for incident in incidents)
    from .models import ResolutionProposal

    pending_corrections = ResolutionProposal.objects.filter(
        round=round, missionresolution__isnull=True
    ).exists()
    latest = latest_snapshot(round)
    blockers = list(dict.fromkeys(gaps + config_errors))
    if open_incidents:
        blockers.append(f"{open_incidents} material incident(s) remain open.")
    if pending_corrections:
        blockers.append("Review or reject pending score corrections before finalization.")
    reviewed_paper = AuditEvent.objects.filter(
        action__in=["approve_paper", "reject_paper"], after__request__round_id=round.pk
    ).values_list("after__request__proposal_id", flat=True)
    if PaperProposal.objects.filter(round=round).exclude(pk__in=list(reviewed_paper)).exists():
        blockers.append("Review or reject pending paper evidence before finalization.")
    if cutoff_tie:
        blockers.append("A qualification cutoff tie requires reviewed reserve-clue evidence.")
    if latest is None or latest.status != "PROVISIONAL":
        blockers.append("Publish provisional results before finalization.")
    elif latest.appeal_deadline is None or now < latest.appeal_deadline:
        blockers.append("The published appeal window is still open.")
    if round.state == "FINALIZED":
        blockers.append("Final results cannot be replaced through ordinary publication.")
    evidence = {
        "attempt_id": str(round.attempt_id),
        "rules_digest": round.rules_digest,
        "clock": {"budget": round.active_budget_ms, "elapsed": round.accumulated_active_ms},
        "teams": [
            {"id": team.pk, "code": team.code, "name": team.name, "status": team.status}
            for team in teams
        ],
        "missions": [
            {
                "id": item.pk,
                "public_id": item.public_id,
                "available": item.available,
                "voided": item.is_void,
                "points": item.points,
                "answer_verifiers": item.answer_verifiers,
            }
            for item in missions
        ],
        "completions": list(
            Completion.objects.filter(mission__round=round).order_by("pk").values()
        ),
        "decisions": list(
            SubmissionDecision.objects.filter(round=round, outcome__in=["accepted", "incorrect"])
            .order_by("pk")
            .values()
        ),
        "phases": list(RoundPhase.objects.filter(round=round).order_by("pk").values()),
        "incidents": list(Incident.objects.filter(round=round).order_by("pk").values()),
        "resolutions": list(
            MissionResolution.objects.filter(mission__round=round).order_by("pk").values()
        ),
        "paper_slips": list(PaperSlip.objects.filter(round=round).order_by("pk").values()),
        "paper_window": list(PaperWindow.objects.filter(round=round).values()),
    }
    return {
        "round_id": round.pk,
        "number": round.number,
        "attempt_no": round.attempt_no,
        "title": round.title,
        "state": round.state,
        "control_version": round.control_version,
        "rules_digest": round.rules_digest,
        "evidence_digest": digest(evidence),
        "entries": entries,
        "cut_count": cut,
        "cutoff_tie": cutoff_tie,
        "max_score": maximum,
        "open_material_incidents": open_incidents,
        "evidence_gaps": list(dict.fromkeys(gaps)),
        "configuration_errors": config_errors,
        "finalization_blockers": blockers,
        "latest_snapshot_id": latest.pk if latest else None,
        "appeal_deadline": latest.appeal_deadline.isoformat()
        if latest and latest.appeal_deadline
        else None,
        "server_time": now.isoformat(),
    }


def validate_request(data):
    try:
        action_id = uuid.UUID(data.get("action_id"))
    except (ValueError, TypeError, AttributeError):
        raise ApiProblem("invalid_request", "Supply a valid action UUID.") from None
    reason = data.get("reason")
    if not isinstance(reason, str) or not reason.strip() or len(reason) > 2000:
        raise ApiProblem("invalid_request", "Supply a reason of at most 2000 characters.")
    return action_id, reason


def audit_replay(action_id, fingerprint):
    existing = AuditEvent.objects.filter(action_id=action_id).first()
    if existing:
        if existing.after.get("request") != fingerprint:
            raise ApiProblem("action_conflict", "This action UUID was used differently.", 409)
        return existing.after["response"]
    return None


def record_action(action_id, actor, action, reason, fingerprint, response):
    try:
        with transaction.atomic():
            AuditEvent.objects.create(
                action_id=action_id,
                actor=actor,
                action=action,
                reason=reason,
                after={"request": fingerprint, "response": response},
            )
    except IntegrityError:
        raise ApiProblem("action_conflict", "This action UUID was already used.", 409) from None


def final_qualifiers(round, preview, data):
    blockers = [item for item in preview["finalization_blockers"] if "cutoff tie" not in item]
    if blockers:
        raise ApiProblem("finalization_blocked", " ".join(blockers), 409)
    if data.get("evidence_confirmed") is not True:
        raise ApiProblem(
            "evidence_required", "Confirm review of roster, scoring and evidence coverage."
        )
    eligible = [entry["team_code"] for entry in preview["entries"] if entry["eligible"]]
    order = data.get("tie_order", [])
    refs = data.get("tie_evidence", [])
    tied = preview["cutoff_tie"]
    if tied:
        if (
            round.rules_snapshot["rules"].get("qualification_tie_policy")
            != "supervised_reserve_clue"
            or not isinstance(order, list)
            or any(not isinstance(code, str) for code in order)
            or len(order) != len(tied)
            or set(order) != set(tied)
            or not isinstance(refs, list)
            or not refs
            or any(not isinstance(ref, str) or not ref.strip() or len(ref) > 500 for ref in refs)
            or not isinstance(data.get("tie_reason"), str)
            or not data["tie_reason"].strip()
        ):
            raise ApiProblem(
                "unresolved_tie",
                "Supply tied teams in reserve-clue order, evidence references and a tie reason.",
                409,
            )
        positions = [eligible.index(code) for code in tied]
        for position, code in zip(positions, order, strict=True):
            eligible[position] = code
    elif order or refs or data.get("tie_reason"):
        raise ApiProblem("invalid_tie", "No cutoff tie requires a reserve-clue decision.")
    return eligible[: preview["cut_count"]]


@transaction.atomic
def propose_result(round_id, actor, data):
    require_result_role(actor)
    action_id, reason = validate_request(data)
    round = locked_round(round_id)
    fingerprint = {**data, "kind": "propose_result", "round_id": round_id, "actor_id": actor.pk}
    if original := audit_replay(action_id, fingerprint):
        return original
    preview = build_preview(round, database_now())
    status = data.get("status")
    if (
        not isinstance(status, str)
        or status not in {"PROVISIONAL", "FINAL"}
        or round.state not in {"ENDED", "PROVISIONAL"}
    ):
        raise ApiProblem(
            "invalid_transition", "Propose provisional or final results for an ended round.", 409
        )
    if (
        type(data.get("expected_version")) is not int
        or data.get("expected_version") != round.control_version
        or data.get("evidence_digest") != preview["evidence_digest"]
    ):
        raise ApiProblem(
            "stale_evidence", "Evidence or round version changed. Refresh and review again.", 409
        )
    if preview["evidence_gaps"] or preview["configuration_errors"]:
        raise ApiProblem(
            "evidence_gap",
            " ".join(preview["evidence_gaps"] + preview["configuration_errors"]),
            409,
        )
    qualifiers = final_qualifiers(round, preview, data) if status == "FINAL" else []
    if status == "PROVISIONAL" and any(
        data.get(key) for key in ("tie_order", "tie_evidence", "tie_reason")
    ):
        raise ApiProblem("invalid_tie", "Reserve-clue decisions belong to the final proposal.")
    proposal = ResultProposal.objects.create(
        round=round,
        maker=actor,
        target_status=status,
        expected_version=round.control_version,
        evidence_digest=preview["evidence_digest"],
        reason=reason,
        payload={
            "preview": preview,
            "qualifiers": qualifiers,
            "tie_order": data.get("tie_order", []),
            "tie_evidence": data.get("tie_evidence", []),
            "tie_reason": data.get("tie_reason", ""),
            "evidence_confirmed": data.get("evidence_confirmed", False),
        },
    )
    response = {"proposal_id": proposal.pk, "status": status}
    record_action(action_id, actor, "propose_result", reason, fingerprint, response)
    return response


@transaction.atomic
def approve_result(round_id, actor, data):
    require_result_role(actor, review=True)
    require_staff_permission(actor, "verify_evidence")
    action_id, reason = validate_request(data)
    round = locked_round(round_id)
    fingerprint = {**data, "kind": "approve_result", "round_id": round_id, "actor_id": actor.pk}
    if original := audit_replay(action_id, fingerprint):
        return original
    if type(data.get("proposal_id")) is not int or data["proposal_id"] <= 0:
        raise ApiProblem("invalid_request", "Supply a valid proposal ID.")
    proposal = (
        ResultProposal.objects.select_related("maker")
        .filter(pk=data["proposal_id"], round=round)
        .first()
    )
    if proposal is None:
        raise ApiProblem("not_found", "Result proposal not found.", 404)
    if proposal.maker_id == actor.pk:
        raise ApiProblem(
            "independent_reviewer",
            "A different authorized reviewer must publish this proposal.",
            403,
        )
    if not has_role(proposal.maker, "control_round", "adjudicate"):
        raise ApiProblem("maker_unauthorized", "The proposal's maker is no longer authorized.", 409)
    if ResultSnapshot.objects.filter(proposal=proposal).exists():
        raise ApiProblem("already_published", "This proposal has already been published.", 409)
    if round.state not in {"ENDED", "PROVISIONAL"}:
        raise ApiProblem(
            "invalid_transition",
            "Final results cannot be replaced through ordinary publication.",
            409,
        )
    now = database_now()
    preview = build_preview(round, now)
    if (
        proposal.expected_version != round.control_version
        or proposal.evidence_digest != preview["evidence_digest"]
    ):
        raise ApiProblem(
            "stale_evidence",
            "Evidence changed after the proposal. Create and review a fresh proposal.",
            409,
        )
    if preview["evidence_gaps"] or preview["configuration_errors"]:
        raise ApiProblem("evidence_gap", "Resolve the evidence gaps before publication.", 409)
    if proposal.target_status == "FINAL":
        if data.get("evidence_confirmed") is not True:
            raise ApiProblem(
                "evidence_required", "Independently confirm roster, scoring and evidence coverage."
            )
        qualifiers = final_qualifiers(round, preview, proposal.payload)
    else:
        qualifiers = []
    previous = latest_snapshot(round)
    snapshot = ResultSnapshot.objects.create(
        round=round,
        revision=previous.revision + 1 if previous else 1,
        status=proposal.target_status,
        ranked_entries=preview["entries"],
        qualifier_codes=qualifiers,
        cut_count=preview["cut_count"],
        rules_digest=round.rules_digest,
        evidence_digest=preview["evidence_digest"],
        maker=proposal.maker,
        approver=actor,
        published_at=now,
        supersedes=previous,
        proposal=proposal,
        appeal_deadline=now + timedelta(minutes=round.rules_snapshot["rules"]["appeal_minutes"])
        if proposal.target_status == "PROVISIONAL"
        else previous.appeal_deadline,
        metadata={
            "max_score": preview["max_score"],
            "cutoff_tie": preview["cutoff_tie"],
            "open_material_incidents": preview["open_material_incidents"],
            "tie_order": proposal.payload["tie_order"],
            "tie_reason": proposal.payload["tie_reason"],
            "publication_reason": proposal.reason,
            "review_reason": reason,
        },
    )
    round.state = "FINALIZED" if snapshot.status == "FINAL" else "PROVISIONAL"
    round.control_version += 1
    round.save(update_fields=["state", "control_version"])
    response = {
        "snapshot_id": snapshot.pk,
        "revision": snapshot.revision,
        "status": snapshot.status,
        "qualifier_codes": snapshot.qualifier_codes,
    }
    record_action(action_id, actor, "publish_result", reason, fingerprint, response)
    return response


@transaction.atomic
def manage_incident(round_id, actor, data):
    action = data.get("action")
    if action == "open":
        require_result_role(actor)
    elif action == "close":
        require_staff_permission(actor, "verify_evidence")
    else:
        raise ApiProblem("invalid_request", "Choose open or close incident.")
    action_id, reason = validate_request(data)
    round = locked_round(round_id)
    fingerprint = {**data, "kind": "result_incident", "round_id": round_id, "actor_id": actor.pk}
    if original := audit_replay(action_id, fingerprint):
        return original
    if round.state == "FINALIZED" and action == "open" and data.get("category") != "SCORING":
        raise ApiProblem(
            "finalized", "Use a reviewed scoring correction for finalized results.", 409
        )
    refs = data.get("evidence_refs", [])
    if not isinstance(refs, list) or any(
        not isinstance(ref, str) or not ref.strip() or len(ref) > 500 for ref in refs
    ):
        raise ApiProblem("invalid_request", "Supply evidence references as a list of strings.")
    if action == "open":
        if (
            not isinstance(data.get("category"), str)
            or data.get("category") not in {"APPEAL", "EVIDENCE_GAP", "SCORING", "OTHER"}
            or type(data.get("material")) is not bool
        ):
            raise ApiProblem("invalid_request", "Choose an incident category and material flag.")
        incident = Incident.objects.create(
            round=round,
            owner=actor,
            category=data["category"],
            affected_scope={"summary": reason},
            opened_at=database_now(),
            evidence_references=refs,
            material=data["material"],
        )
    else:
        if type(data.get("incident_id")) is not int:
            raise ApiProblem("invalid_request", "Supply an incident ID.")
        incident = Incident.objects.filter(pk=data["incident_id"], round=round).first()
        if incident is None:
            raise ApiProblem("not_found", "Incident not found.", 404)
        if incident.owner_id == actor.pk:
            raise ApiProblem(
                "independent_reviewer", "A different verifier must close the incident.", 403
            )
        if incident.closed_at is not None:
            raise ApiProblem("already_closed", "This incident is already closed.", 409)
        if not refs:
            raise ApiProblem("evidence_required", "Reference the evidence supporting this closure.")
        incident.closed_at = database_now()
        incident.decision = reason
        incident.evidence_references = [*incident.evidence_references, *refs]
        incident.save(update_fields=["closed_at", "decision", "evidence_references"])
    response = {"incident_id": incident.pk, "closed": incident.closed_at is not None}
    record_action(action_id, actor, f"{action}_result_incident", reason, fingerprint, response)
    return response
