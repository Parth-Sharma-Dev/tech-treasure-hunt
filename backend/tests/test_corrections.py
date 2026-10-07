import uuid
from datetime import timedelta

import pytest
from django.utils import timezone
from test_results import (
    approve,
    completion,
    proposal,
)
from test_results import (
    ended_hunt as _ended_hunt,
)

from competition.answers import answer_digest
from competition.api import ApiProblem
from competition.corrections import approve_correction, propose_correction
from competition.models import (
    Completion,
    Incident,
    MissionResolution,
    ResultSnapshot,
    Round,
    SubmissionDecision,
)
from competition.participant import round_eligible
from competition.results import build_preview

pytestmark = pytest.mark.django_db
ended_hunt = _ended_hunt


def correction(hunt, kind="ALTERNATE", **extra):
    round, missions, _, maker, _, _ = hunt
    round.refresh_from_db()
    data = {
        "action_id": str(uuid.uuid4()),
        "correction_type": kind,
        "mission_id": missions[0].pk,
        "reason": "Synthetic correction",
        "public_summary": "Reviewed correction to clue one.",
        "answer": "1024",
        "evidence_refs": ["synthetic-evidence"],
        "expected_version": round.control_version,
        **extra,
    }
    return propose_correction(round.pk, maker, data), data


def review(hunt, proposed, actor=None, **extra):
    round, _, _, _, reviewer, _ = hunt
    data = {
        "action_id": str(uuid.uuid4()),
        "proposal_id": proposed["correction_proposal_id"],
        "reason": "Independently checked",
        "evidence_confirmed": True,
        **extra,
    }
    return approve_correction(round.pk, actor or reviewer, data), data


def wrong(hunt, outcome="incorrect", elapsed=5000):
    round, missions, teams, _, _, start = hunt
    return SubmissionDecision.objects.create(
        team=teams[0],
        round=round,
        mission=missions[0],
        idempotency_key=uuid.uuid4(),
        request_fingerprint="f" * 64,
        answer_hmac=answer_digest(missions[0].pk, "v1", "1024"),
        answer_key_version="v1",
        rules_version="v1",
        outcome=outcome,
        ingress_at=start + timedelta(milliseconds=elapsed),
        admitted_at=start + timedelta(milliseconds=elapsed),
        active_elapsed_ms=elapsed,
        response_snapshot={"outcome": outcome},
    )


def test_alternate_preserves_wrong_and_rebuilds_earlier_completion(ended_hunt):
    original = wrong(ended_hunt)
    wrong(ended_hunt, outcome="cooldown", elapsed=2000)
    accepted = completion(ended_hunt, elapsed=20000)
    proposed, data = correction(ended_hunt)
    assert propose_correction(ended_hunt[0].pk, ended_hunt[3], data) == proposed
    with pytest.raises(ApiProblem, match="different verifier"):
        review(ended_hunt, proposed, actor=ended_hunt[3])
    response, request = review(ended_hunt, proposed)
    assert approve_correction(ended_hunt[0].pk, ended_hunt[4], request) == response
    accepted.refresh_from_db()
    original.refresh_from_db()
    assert original.outcome == "incorrect"
    assert accepted.effective_active_ms == 5000 and accepted.source_decision_id is None
    assert response["reclassified_decisions"] == 1
    assert MissionResolution.objects.count() == 1
    preview = build_preview(ended_hunt[0], timezone.now())
    assert preview["evidence_gaps"] == []
    assert preview["entries"][0]["score"] == 1 and preview["entries"][0]["tie_time_ms"] == 5000


def test_void_preserves_receipt_but_removes_score_and_denominator(ended_hunt):
    accepted = completion(ended_hunt)
    receipt = accepted.source_decision.response_snapshot["receipt"]
    proposed, _ = correction(ended_hunt, kind="VOID")
    review(ended_hunt, proposed)
    preview = build_preview(ended_hunt[0], timezone.now())
    assert preview["max_score"] == 1 and preview["entries"][0]["score"] == 0
    assert preview["entries"][0]["tie_time_ms"] is None
    accepted.source_decision.refresh_from_db()
    assert accepted.source_decision.response_snapshot["receipt"] == receipt


def test_changed_evidence_rejects_correction(ended_hunt):
    proposed, _ = correction(ended_hunt)
    wrong(ended_hunt)
    with pytest.raises(ApiProblem, match="Evidence changed"):
        review(ended_hunt, proposed)
    assert not MissionResolution.objects.exists()


def test_postfinal_requires_explicit_supersession_and_restarts_appeal(ended_hunt):
    completion(ended_hunt)
    published = approve(ended_hunt, proposal(ended_hunt))
    snapshot = ResultSnapshot.objects.get(pk=published["snapshot_id"])
    when = snapshot.appeal_deadline + timedelta(seconds=1)
    approve(ended_hunt, proposal(ended_hunt, "FINAL", now=when), now=when)
    proposed, _ = correction(ended_hunt, kind="VOID")
    with pytest.raises(ApiProblem, match="superseded"):
        review(ended_hunt, proposed)
    response, _ = review(ended_hunt, proposed, supersession_confirmed=True)
    assert response["state"] == "PROVISIONAL"
    latest = ResultSnapshot.objects.latest("revision")
    assert latest.status == "PROVISIONAL" and latest.qualifier_codes == []
    assert latest.supersedes.status == "FINAL" and latest.appeal_deadline > timezone.now()


def test_reject_stale_correction_closes_incident_without_changing_scores(ended_hunt):
    proposed, _ = correction(ended_hunt)
    wrong(ended_hunt)
    response, _ = review(ended_hunt, proposed, reject=True)
    assert response["rejected"] and not Completion.objects.exists()
    resolution = MissionResolution.objects.get(pk=response["resolution_id"])
    assert resolution.correction_type == "REJECTED" and resolution.incident.closed_at


def test_only_latest_round1_attempt_allows_new_play(ended_hunt):
    round, _, teams, _, _, _ = ended_hunt
    assert round_eligible(teams[0], round)
    latest = Round.objects.create(number=1, attempt_no=2, title="Next rehearsal", is_demo=True)
    assert not round_eligible(teams[0], round)
    assert round_eligible(teams[0], latest)


def test_postfinal_progression_impact_pauses_dependent_play_and_keeps_review_private(ended_hunt):
    completion(ended_hunt)
    published = approve(ended_hunt, proposal(ended_hunt))
    snapshot = ResultSnapshot.objects.get(pk=published["snapshot_id"])
    when = snapshot.appeal_deadline + timedelta(seconds=1)
    approve(ended_hunt, proposal(ended_hunt, "FINAL", now=when), now=when)
    now = timezone.now()
    next_round = Round.objects.create(
        number=2,
        title="Synthetic dependent play",
        is_demo=True,
        state="LIVE",
        phase_started_at=now,
        live_started_at=now,
        deadline_at=now + timedelta(minutes=1),
        delivery_mode="EXTERNAL",
    )
    proposed, _ = correction(ended_hunt, kind="VOID")
    with pytest.raises(ApiProblem, match="dependent rounds"):
        review(ended_hunt, proposed, supersession_confirmed=True)
    review(ended_hunt, proposed, supersession_confirmed=True, progression_impact_confirmed=True)
    next_round.refresh_from_db()
    assert next_round.state == "FROZEN"
    assert Incident.objects.filter(
        round=next_round, category="QUALIFICATION_IMPACT", closed_at__isnull=True
    ).exists()
    latest = ResultSnapshot.objects.filter(round=ended_hunt[0]).latest("revision")
    assert (
        latest.metadata["review_reason"] == "An independent reviewer approved the score correction."
    )
