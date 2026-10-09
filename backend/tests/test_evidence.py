import uuid
from datetime import timedelta

import pytest
from django.core.signing import Signer
from django.test import Client
from django.utils import timezone
from test_results import completion
from test_results import ended_hunt as _ended_hunt

from competition.api import ApiProblem
from competition.evidence import (
    EXPORT_SIGNER,
    approve_recovery,
    compare_bundle,
    evidence_page,
    export_objects,
    inventory,
    make_bundle,
    propose_recovery,
    read_bundle,
    spreadsheet_cell,
    verify_receipts,
)
from competition.models import Completion, Incident, SubmissionDecision, Team, TeamSession
from competition.results import build_preview

pytestmark = pytest.mark.django_db
ended_hunt = _ended_hunt


def test_signed_inventory_identifies_missing_decision_and_detects_tampering(ended_hunt):
    round = ended_hunt[0]
    item = completion(ended_hunt)
    bundle = make_bundle(round)
    with pytest.raises(ApiProblem, match="signature"):
        read_bundle(bundle["signed_bundle"] + "damaged", round)
    payload = read_bundle(bundle["signed_bundle"], round)
    assert compare_bundle(round, payload)["missing"] == []
    Completion.objects.all().delete()
    SubmissionDecision.objects.filter(pk=item.source_decision_id)._raw_delete("default")
    assert len(compare_bundle(round, payload)["missing"]) == 2


def test_legacy_round1_checkpoint_still_reconciles(ended_hunt):
    round, _, _, maker, reviewer, _ = ended_hunt
    item = completion(ended_hunt)
    payload = read_bundle(make_bundle(round)["signed_bundle"], round)
    payload["format"] = "round-evidence-v1"
    payload["objects"] = export_objects(round, extended=False)
    payload["inventory"] = inventory(payload["objects"])
    signed = EXPORT_SIGNER.sign_object(payload)
    Completion.objects.all().delete()
    SubmissionDecision.objects.filter(pk=item.source_decision_id)._raw_delete("default")
    proposed = propose_recovery(
        round.pk,
        maker,
        {
            "action_id": str(uuid.uuid4()),
            "expected_version": round.control_version,
            "reason": "Legacy checkpoint recovery",
            "evidence_refs": ["legacy-checkpoint"],
            "signed_bundle": signed,
        },
    )
    approve_recovery(
        round.pk,
        reviewer,
        {
            "action_id": str(uuid.uuid4()),
            "proposal_id": proposed["recovery_proposal_id"],
            "reason": "Checked legacy checkpoint",
            "evidence_confirmed": True,
        },
    )
    assert Completion.objects.count() == 1


def test_reviewed_recovery_restores_exact_decision_once_and_revokes_sessions(ended_hunt):
    round, _, teams, maker, reviewer, _ = ended_hunt
    item = completion(ended_hunt)
    original = item.source_decision.response_snapshot
    bundle = make_bundle(round)
    Completion.objects.all().delete()
    SubmissionDecision.objects.filter(pk=item.source_decision_id)._raw_delete("default")
    TeamSession.objects.create(
        team=teams[0],
        session_key="synthetic-private-cookie",
        session_version=1,
        created_at=timezone.now(),
        last_seen_at=timezone.now(),
        expires_at=timezone.now() + timedelta(hours=1),
    )
    request = {
        "action_id": str(uuid.uuid4()),
        "expected_version": round.control_version,
        "reason": "Recover synthetic checkpoint",
        "evidence_refs": ["checkpoint-log"],
        "signed_bundle": bundle["signed_bundle"],
    }
    proposed = propose_recovery(round.pk, maker, request)
    assert (
        TeamSession.objects.get().revoked_at
        and Team.objects.get(pk=teams[0].pk).session_version == 2
    )
    review = {
        "action_id": str(uuid.uuid4()),
        "proposal_id": proposed["recovery_proposal_id"],
        "reason": "Verified complete checkpoint inventory",
        "evidence_confirmed": True,
    }
    with pytest.raises(ApiProblem, match="different verifier"):
        approve_recovery(round.pk, maker, review)
    result = approve_recovery(round.pk, reviewer, review)
    assert approve_recovery(round.pk, reviewer, review) == result
    assert Completion.objects.count() == 1
    assert SubmissionDecision.objects.get().response_snapshot == original
    round.refresh_from_db()
    assert build_preview(round, timezone.now())["evidence_gaps"] == []
    assert not Incident.objects.filter(category="RECOVERY", closed_at__isnull=True).exists()


def test_exports_are_bounded_and_cursor_rejects_changed_evidence(ended_hunt):
    round, _, _, maker, _, _ = ended_hunt
    completion(ended_hunt)
    page = evidence_page(round.pk, maker, "mission", limit=1)
    assert len(page["objects"]) == 1 and page["next_cursor"]
    second = evidence_page(round.pk, maker, "mission", cursor=page["next_cursor"], limit=1)
    assert second["objects"][0]["pk"] != page["objects"][0]["pk"]
    with pytest.raises(ApiProblem, match="from 1 to 500"):
        evidence_page(round.pk, maker, "mission", limit=501)
    completion(ended_hunt, team_index=1)
    with pytest.raises(ApiProblem, match="changed during export"):
        evidence_page(round.pk, maker, "mission", cursor=page["next_cursor"], limit=1)


def test_recovery_cannot_overwrite_newer_unbacked_evidence(ended_hunt):
    round, _, _, maker, reviewer, _ = ended_hunt
    bundle = make_bundle(round)
    completion(ended_hunt)
    proposed = propose_recovery(
        round.pk,
        maker,
        {
            "action_id": str(uuid.uuid4()),
            "expected_version": round.control_version,
            "reason": "Synthetic old checkpoint",
            "evidence_refs": ["checkpoint"],
            "signed_bundle": bundle["signed_bundle"],
        },
    )
    with pytest.raises(ApiProblem, match="Additional evidence"):
        approve_recovery(
            round.pk,
            reviewer,
            {
                "action_id": str(uuid.uuid4()),
                "proposal_id": proposed["recovery_proposal_id"],
                "reason": "Review old checkpoint",
                "evidence_confirmed": True,
            },
        )
    assert Completion.objects.count() == 1 and Incident.objects.get().closed_at is None


def test_receipt_verification_distinguishes_invalid_from_missing_evidence(ended_hunt):
    round, _, teams, maker, _, _ = ended_hunt
    item = completion(ended_hunt)
    token = Signer(salt="competition.accepted-receipt.v1").sign_object(
        {
            "decision_id": str(item.source_decision_id),
            "team_code": teams[0].code,
            "round_id": round.pk,
            "attempt_id": str(round.attempt_id),
            "outcome": "accepted",
        }
    )
    SubmissionDecision.objects.filter(pk=item.source_decision_id).update(
        response_snapshot={"receipt": token}
    )
    result = verify_receipts(round.pk, maker, [token, "invalid-signature"])
    assert [row["status"] for row in result["receipts"]] == ["verified", "invalid"]
    Completion.objects.all().delete()
    SubmissionDecision.objects.all()._raw_delete("default")
    assert verify_receipts(round.pk, maker, [token])["receipts"][0]["status"] == "missing_decision"


@pytest.mark.parametrize("value", ["=cmd()", "  +formula", "-formula", "@formula", "\tformula"])
def test_spreadsheet_exports_neutralize_formula_cells(value):
    assert spreadsheet_cell(value).startswith("'")


def test_new_staff_endpoints_deny_participants_and_require_csrf(ended_hunt):
    round, _, teams, _, reviewer, _ = ended_hunt
    client = Client()
    client.force_login(teams[0].user)
    base = f"/api/staff/rounds/{round.pk}"
    assert client.get(base + "/exports/bundle").status_code == 403
    for endpoint in ["resolutions", "paper", "recovery", "receipts/verify"]:
        assert (
            client.post(
                base + "/" + endpoint, data={"action": "approve"}, content_type="application/json"
            ).status_code
            == 403
        )
    staff = Client(enforce_csrf_checks=True)
    staff.force_login(reviewer)
    assert (
        staff.post(
            base + "/paper", data={"action": "approve"}, content_type="application/json"
        ).status_code
        == 403
    )
