"""One-way paper activation and independently checked numbered slips."""

import re
from datetime import timedelta

from django.db import transaction
from django.utils.dateparse import parse_datetime
from django.utils.timezone import is_aware
from django.views.decorators.debug import sensitive_variables

from .answers import answer_digest
from .api import ApiProblem
from .clock import close_phase, database_now, milliseconds
from .corrections import evidence_refs
from .models import (
    AuditEvent,
    Completion,
    Incident,
    Mission,
    MissionResolution,
    PaperProposal,
    PaperSlip,
    PaperWindow,
    Team,
)
from .results import (
    audit_replay,
    digest,
    has_role,
    locked_round,
    record_action,
    require_result_role,
    validate_request,
)
from .rules import require_staff_permission


def paper_digest(round):
    return digest(
        {
            "version": round.control_version,
            "mode": round.play_mode,
            "missions": list(
                Mission.objects.filter(round=round)
                .order_by("pk")
                .values("id", "is_void", "answer_verifiers")
            ),
            "slips": list(PaperSlip.objects.filter(round=round).order_by("pk").values()),
            "completions": list(
                Completion.objects.filter(mission__round=round).order_by("pk").values()
            ),
        }
    )


def require_hunt(round):
    if round.number != 1 or round.delivery_mode != "ONLINE_HUNT":
        raise ApiProblem("unsupported_round", "Paper reconciliation is for Round 1 only.", 409)


@transaction.atomic
@sensitive_variables("answer", "data")
def propose_paper(round_id, actor, data):
    require_result_role(actor)
    action_id, reason = validate_request(data)
    round = locked_round(round_id)
    require_hunt(round)
    kind = data.get("kind")
    payload = {"evidence_refs": evidence_refs(data)}
    if kind == "ACTIVATE":
        desks = data.get("assigned_desks")
        codes = set(
            Team.objects.filter(is_demo=round.is_demo, status="ACTIVE").values_list(
                "code", flat=True
            )
        )
        if (
            not isinstance(desks, dict)
            or set(desks) != codes
            or any(
                not isinstance(desk, str) or not desk.strip() or len(desk) > 100
                for desk in desks.values()
            )
        ):
            raise ApiProblem("invalid_request", "Assign every active team to a named paper desk.")
        payload.update(
            {
                "assigned_desks": desks,
                "clock_evidence": evidence_refs({"evidence_refs": data.get("clock_evidence")}),
                "writer_isolation_evidence": evidence_refs(
                    {"evidence_refs": data.get("writer_isolation_evidence")}
                ),
            }
        )
    elif kind == "SLIP":
        answer = data.get("answer")
        if not isinstance(answer, str) or re.fullmatch(r"[0-9]{4}", answer) is None:
            raise ApiProblem("invalid_format", "Supply four ASCII digits for the recorded answer.")
        mission = (
            Mission.objects.filter(
                pk=data.get("mission_id"), round=round, is_practice=False
            ).first()
            if type(data.get("mission_id")) is int
            else None
        )
        team = (
            Team.objects.filter(code=data.get("team_code"), is_demo=round.is_demo).first()
            if isinstance(data.get("team_code"), str)
            else None
        )
        if mission is None or team is None:
            raise ApiProblem("not_found", "Team or competitive mission not found.", 404)
        try:
            when = parse_datetime(data.get("evaluated_at", ""))
        except (TypeError, ValueError):
            when = None
        if when is None or not is_aware(when):
            raise ApiProblem("invalid_request", "Supply the official slip time with its timezone.")
        number, desk = data.get("slip_number"), data.get("desk")
        if (
            not isinstance(number, str)
            or not number.strip()
            or len(number) > 64
            or not isinstance(desk, str)
            or not desk.strip()
            or len(desk) > 100
        ):
            raise ApiProblem("invalid_request", "Supply a numbered slip and assigned desk.")
        payload.update(
            {
                "team_id": team.pk,
                "mission_id": mission.pk,
                "slip_number": number.strip(),
                "desk": desk,
                "evaluated_at": when.isoformat(),
                "blocked": data.get("blocked") is True,
                "verifiers": [
                    {
                        "version": item["version"],
                        "digest": answer_digest(mission.pk, item["version"], answer),
                    }
                    for item in mission.answer_verifiers
                ],
            }
        )
    else:
        raise ApiProblem("invalid_request", "Choose paper activation or slip reconciliation.")
    fingerprint = {
        "kind": "paper_propose",
        "round_id": round_id,
        "actor_id": actor.pk,
        "reason": reason,
        "payload": payload,
        "proposal_kind": kind,
        "expected_version": data.get("expected_version"),
    }
    if original := audit_replay(action_id, fingerprint):
        return original
    if (
        type(data.get("expected_version")) is not int
        or data["expected_version"] != round.control_version
    ):
        raise ApiProblem("stale_evidence", "Refresh the paper desk before proposing.", 409)
    if kind == "ACTIVATE" and (
        round.state != "FROZEN"
        or round.play_mode != "ONLINE"
        or round.accumulated_active_ms >= round.active_budget_ms
    ):
        raise ApiProblem(
            "invalid_transition",
            "Pause online play with active time remaining before paper activation.",
            409,
        )
    if kind == "SLIP" and (
        round.play_mode != "PAPER" or round.state not in ["LIVE", "ENDED", "PROVISIONAL"]
    ):
        raise ApiProblem(
            "invalid_transition",
            "Reconcile paper slips during paper play or before final results.",
            409,
        )
    proposal = PaperProposal.objects.create(
        round=round,
        kind=kind,
        payload=payload,
        maker=actor,
        reason=reason,
        expected_version=round.control_version,
        evidence_digest=paper_digest(round),
    )
    response = {"paper_proposal_id": proposal.pk, "kind": kind}
    record_action(action_id, actor, "propose_paper", reason, fingerprint, response)
    return response


@transaction.atomic
def approve_paper(round_id, actor, data):
    require_staff_permission(actor, "verify_evidence")
    action_id, reason = validate_request(data)
    round = locked_round(round_id)
    require_hunt(round)
    fingerprint = {**data, "kind": "paper_approve", "round_id": round_id, "actor_id": actor.pk}
    if original := audit_replay(action_id, fingerprint):
        return original
    proposal = (
        PaperProposal.objects.filter(pk=data.get("proposal_id"), round=round).first()
        if type(data.get("proposal_id")) is int
        else None
    )
    if proposal is None:
        raise ApiProblem("not_found", "Paper proposal not found.", 404)
    if actor.pk == proposal.maker_id:
        raise ApiProblem(
            "independent_reviewer", "A different verifier must review paper evidence.", 403
        )
    if (
        not has_role(proposal.maker, "control_round", "adjudicate")
        or data.get("evidence_confirmed") is not True
    ):
        raise ApiProblem(
            "evidence_required",
            "Check maker authorization and independently confirm the paper evidence.",
        )
    if AuditEvent.objects.filter(
        action__in=["approve_paper", "reject_paper"],
        after__request__proposal_id=proposal.pk,
        after__request__round_id=round_id,
    ).exists():
        raise ApiProblem("already_applied", "This paper proposal was already reviewed.", 409)
    if data.get("reject") is True:
        response = {"paper_proposal_id": proposal.pk, "rejected": True}
        record_action(action_id, actor, "reject_paper", reason, fingerprint, response)
        return response
    if (
        proposal.expected_version != round.control_version
        or proposal.evidence_digest != paper_digest(round)
    ):
        raise ApiProblem("stale_evidence", "Paper evidence changed; prepare a fresh proposal.", 409)
    now = database_now()
    payload = proposal.payload
    if proposal.kind == "ACTIVATE":
        if round.state != "FROZEN" or round.play_mode != "ONLINE":
            raise ApiProblem(
                "invalid_transition", "Pause online play before activating paper.", 409
            )
        incident = Incident.objects.create(
            round=round,
            category="PAPER_ACTIVATION",
            owner=proposal.maker,
            opened_at=now,
            closed_at=now,
            material=False,
            decision=reason,
            affected_scope={"summary": proposal.reason},
            evidence_references=payload["evidence_refs"],
        )
        remaining = round.active_budget_ms - round.accumulated_active_ms
        if remaining <= 0:
            raise ApiProblem("budget_exhausted", "No active budget remains.", 409)
        close_phase(round, now, actor, reason)
        window = PaperWindow.objects.create(
            round=round,
            incident=incident,
            official_start=now,
            official_end=now + timedelta(milliseconds=remaining),
            active_offset_ms=round.accumulated_active_ms,
            remaining_budget_ms=remaining,
            assigned_desks=payload["assigned_desks"],
            clock_evidence=payload["clock_evidence"],
            writer_isolation_evidence=payload["writer_isolation_evidence"],
            recorder=proposal.maker,
            verifier=actor,
        )
        round.play_mode = "PAPER"
        round.state = "LIVE"
        round.phase_started_at = round.live_started_at = window.official_start
        round.deadline_at = window.official_end
        round.control_version += 1
        round.save()
        response = {
            "paper_window_id": window.pk,
            "official_start": now.isoformat(),
            "official_end": window.official_end.isoformat(),
            "state": "LIVE",
            "play_mode": "PAPER",
        }
    else:
        window = PaperWindow.objects.filter(round=round).first()
        when = parse_datetime(payload["evaluated_at"])
        team = Team.objects.get(pk=payload["team_id"])
        mission = Mission.objects.get(pk=payload["mission_id"])
        if (
            window is None
            or round.play_mode != "PAPER"
            or round.state not in ["LIVE", "ENDED", "PROVISIONAL"]
        ):
            raise ApiProblem(
                "invalid_transition", "Reconcile paper work before final results.", 409
            )
        last = (
            PaperSlip.objects.filter(team=team, mission=mission).order_by("-evaluated_at").first()
        )
        elapsed = window.active_offset_ms + milliseconds(when - window.official_start)
        if (
            team.status != "ACTIVE"
            or window.assigned_desks.get(team.code) != payload["desk"]
            or not mission.available
            or mission.is_void
            or when < window.official_start
            or when > min(now, window.official_end)
            or (round.state != "LIVE" and elapsed > round.accumulated_active_ms)
        ):
            raise ApiProblem(
                "invalid_paper_evidence",
                "Check eligibility, desk assignment, mission and official time.",
                409,
            )
        if last and when < last.evaluated_at:
            raise ApiProblem(
                "out_of_order", "Reconcile each team/mission in official chronological order.", 409
            )
        if PaperSlip.objects.filter(round=round, slip_number=payload["slip_number"]).exists():
            raise ApiProblem(
                "duplicate_slip", "This numbered slip has already been reconciled.", 409
            )
        evaluated = PaperSlip.objects.filter(
            team=team,
            mission=mission,
            outcome__in=["accepted", "incorrect"],
            active_elapsed_ms__gt=elapsed - 60_000,
            active_elapsed_ms__lte=elapsed,
        ).exists()
        completed = Completion.objects.filter(team=team, mission=mission).exists()
        outcome = "blocked" if payload["blocked"] or evaluated or completed else "incorrect"
        matches = [v for v in payload["verifiers"] if v in mission.answer_verifiers]
        verifier = matches[0] if matches else payload["verifiers"][0]
        if outcome == "incorrect" and matches:
            outcome = "accepted"
        slip = PaperSlip.objects.create(
            round=round,
            proposal=proposal,
            team=team,
            mission=mission,
            slip_number=payload["slip_number"],
            desk=payload["desk"],
            evaluated_at=when,
            active_elapsed_ms=elapsed,
            outcome=outcome,
            answer_hmac=verifier["digest"],
            answer_key_version=verifier["version"],
            maker=proposal.maker,
            verifier=actor,
            evidence_references=payload["evidence_refs"],
        )
        if outcome == "accepted":
            resolution = MissionResolution.objects.create(
                mission=mission,
                correction_type="PAPER_ACCEPTED",
                affected_scope={"paper_slip_id": slip.pk, "team_id": team.pk},
                reason=proposal.reason,
                evidence_references=payload["evidence_refs"],
                maker=proposal.maker,
                approver=actor,
                incident=window.incident,
            )
            Completion.objects.create(
                team=team,
                mission=mission,
                source_resolution=resolution,
                effective_at=when,
                effective_active_ms=elapsed,
            )
        response = {"paper_slip_id": slip.pk, "slip_number": slip.slip_number, "outcome": outcome}
    record_action(action_id, actor, "approve_paper", reason, fingerprint, response)
    return response


@transaction.atomic
def end_paper(round_id, actor, data):
    require_staff_permission(actor, "control_round")
    action_id, reason = validate_request(data)
    round = locked_round(round_id)
    fingerprint = {**data, "kind": "paper_end", "round_id": round_id, "actor_id": actor.pk}
    if original := audit_replay(action_id, fingerprint):
        return original
    if round.play_mode != "PAPER" or round.state != "LIVE":
        raise ApiProblem("invalid_transition", "Only live paper play can be ended.", 409)
    if (
        type(data.get("expected_version")) is not int
        or data["expected_version"] != round.control_version
    ):
        raise ApiProblem("stale_evidence", "Refresh before ending paper play.", 409)
    now = database_now()
    close_phase(round, now, actor, reason)
    round.state = "ENDED"
    round.control_version += 1
    round.save()
    response = {"state": "ENDED", "active_elapsed_ms": round.accumulated_active_ms}
    record_action(action_id, actor, "end_paper", reason, fingerprint, response)
    return response
