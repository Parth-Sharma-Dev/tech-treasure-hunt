"""Offline-final restore drills retain native timing, reviewed credit and award history."""

import uuid
from datetime import timedelta
from unittest.mock import patch

import pytest
from django.utils import timezone
from test_buzzer import buzzer as _buzzer
from test_buzzer_scores import final as _final
from test_buzzer_scores import intake, played, publish
from test_later_round_recovery import recover

from competition import models as m
from competition.api import ApiProblem
from competition.buzzer import is_open
from competition.evidence import (
    EXPORT_SIGNER,
    approve_recovery,
    compare_bundle,
    evidence_page,
    export_objects,
    make_bundle,
    propose_recovery,
    read_bundle,
)
from competition.results import build_preview

pytestmark = pytest.mark.django_db
buzzer = _buzzer
final = _final


def checkpoint(final, award=False):
    intake(final, played(final, count=25))
    if award:
        publish(final)
        deadline = (
            m.ResultSnapshot.objects.filter(round=final[0]).latest("revision").appeal_deadline
        )
        with patch(
            "competition.results.database_now", return_value=deadline + timedelta(seconds=1)
        ):
            publish(final, "FINAL")
    final[0].refresh_from_db()
    return make_bundle(final[0])


def test_signed_native_pages_bind_exact_carry_over_and_reject_legacy_final(final):
    bundle = checkpoint(final)
    payload = read_bundle(bundle["signed_bundle"], final[0])
    assert payload["format"] == "round-evidence-v3"
    assert len(payload["carry_over_provenance"]["basis"]) == 4
    assert payload["carry_over_provenance"]["errors"] == []
    assert "session_key" not in str(payload)
    for kind in [
        "buzzerquestion",
        "buzzerwindow",
        "buzzerclosure",
        "buzzerpress",
        "buzzeranswerevidence",
        "buzzerscorerevision",
    ]:
        page = evidence_page(final[0].pk, final[3], kind, limit=1)
        assert len(page["objects"]) == 1 and page["next_cursor"]
    payload["format"] = "round-evidence-v2"
    with pytest.raises(ApiProblem, match="different rules/attempt"):
        read_bundle(EXPORT_SIGNER.sign_object(payload), final[0])


def test_restore_drill_reproduces_original_winner_and_revokes_missing_sessions(final):
    bundle = checkpoint(final, award=True)
    round, _, teams, maker, reviewer = final
    before = export_objects(round)
    expected = build_preview(round, timezone.now())["entries"]
    cookies = set(m.TeamSession.objects.values_list("session_key", flat=True))
    for model in [
        m.BuzzerScoreRevision,
        m.ImportBatch,
        m.BuzzerAnswerEvidence,
        m.BuzzerPress,
        m.BuzzerClosure,
        m.BuzzerWindow,
        m.BuzzerQuestion,
        m.ResultSnapshot,
        m.ResultProposal,
    ]:
        query = (
            model.objects.filter(round=round)
            if any(field.name == "round" for field in model._meta.fields)
            else model.objects.filter(window__round=round)
        )
        query._raw_delete("default")
    m.TeamSession.objects.all()._raw_delete("default")
    # Simulate the older database's pre-publication state as well as absent evidence.
    m.Round.objects.filter(pk=round.pk).update(state="ENDED")
    round.refresh_from_db()
    assert recover(round, maker, reviewer, bundle)["reconciled"]
    round.refresh_from_db()
    assert round.state == "FINALIZED"
    assert build_preview(round, timezone.now())["entries"] == expected
    snapshot = m.ResultSnapshot.objects.filter(round=round).latest("revision")
    assert snapshot.metadata["winner_codes"] == [teams[0].code]
    assert snapshot.qualifier_codes == []
    assert not m.TeamSession.objects.filter(revoked_at__isnull=True).exists()
    assert not cookies.intersection(m.TeamSession.objects.values_list("session_key", flat=True))
    recovered = {(item["model"], str(item["pk"])): item for item in export_objects(round)}
    for item in before:
        if item["model"].startswith("competition.buzzer"):
            assert recovered[(item["model"], str(item["pk"]))] == item
    assert all(
        not is_open(round, window, timezone.now())
        for window in m.BuzzerWindow.objects.filter(round=round)
    )
    assert m.BuzzerScoreRevision.objects.count() == 25


@pytest.mark.parametrize("change", ["new_snapshot", "missing_snapshot", "new_attempt"])
def test_recovery_refuses_different_or_missing_carry_over_dependencies(final, change):
    bundle = checkpoint(final)
    prior = m.Round.objects.get(number=2, is_demo=True)
    if change == "new_snapshot":
        snapshot = m.ResultSnapshot.objects.filter(round=prior).latest("revision")
        snapshot.pk = None
        snapshot._state.adding = True
        snapshot.revision += 1
        snapshot.save()
    elif change == "missing_snapshot":
        m.ResultSnapshot.objects.filter(round=prior)._raw_delete("default")
    else:
        m.Round.objects.create(number=2, attempt_no=2, title="Different attempt", is_demo=True)
    assert compare_bundle(final[0], read_bundle(bundle["signed_bundle"], final[0]))[
        "carry_over_changed"
    ]
    with pytest.raises(ApiProblem, match="Recover earlier rounds first"):
        recover(final[0], final[3], final[4], bundle)
    assert m.Incident.objects.filter(category="RECOVERY", closed_at__isnull=True).exists()


def test_changed_native_completion_is_not_overwritten(final):
    bundle = checkpoint(final)
    m.BuzzerAnswerEvidence.objects.all().update(completed_at=timezone.now())
    with pytest.raises(ApiProblem, match="Immutable evidence differs"):
        recover(final[0], final[3], final[4], bundle)
    assert m.Incident.objects.filter(category="RECOVERY", closed_at__isnull=True).exists()


def test_prior_result_change_during_review_invalidates_recovery(final):
    bundle = checkpoint(final)
    round = final[0]
    proposed = propose_recovery(
        round.pk,
        final[3],
        {
            "action_id": str(uuid.uuid4()),
            "expected_version": round.control_version,
            "reason": "Synthetic review drift",
            "evidence_refs": ["private checkpoint"],
            "signed_bundle": bundle["signed_bundle"],
        },
    )
    m.Round.objects.filter(number=1, is_demo=True).update(rules_digest="different approved rules")
    with pytest.raises(ApiProblem, match="Round changed during recovery review"):
        approve_recovery(
            round.pk,
            final[4],
            {
                "action_id": str(uuid.uuid4()),
                "proposal_id": proposed["recovery_proposal_id"],
                "reason": "Review checkpoint",
                "evidence_confirmed": True,
            },
        )


def test_recovery_preserves_withdrawal_without_rewriting_historical_award(final):
    bundle = checkpoint(final, award=True)
    final[2][0].status = "WITHDRAWN"
    final[2][0].save(update_fields=["status"])
    recover(final[0], final[3], final[4], bundle)
    final[2][0].refresh_from_db()
    assert final[2][0].status == "WITHDRAWN"
    assert m.ResultSnapshot.objects.filter(round=final[0]).latest("revision").metadata[
        "winner_codes"
    ] == [final[2][0].code]


def test_completed_earlier_recovery_bookkeeping_does_not_change_carried_basis(final):
    bundle = checkpoint(final)
    prior = m.Round.objects.get(number=2, is_demo=True)
    prior.control_version += 1
    prior.save(update_fields=["control_version"])
    m.Incident.objects.create(
        round=prior,
        owner=final[3],
        category="RECOVERY",
        material=True,
        opened_at=timezone.now(),
        closed_at=timezone.now(),
        decision="Earlier recovery reviewed",
    )
    assert recover(final[0], final[3], final[4], bundle)["reconciled"]
