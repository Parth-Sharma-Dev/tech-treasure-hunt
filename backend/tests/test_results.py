import os
import shutil
import subprocess
import uuid
from concurrent.futures import ThreadPoolExecutor
from contextlib import nullcontext
from datetime import timedelta
from pathlib import Path
from threading import Barrier
from unittest.mock import patch

import pytest
from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied
from django.core.signing import Signer
from django.db import connections
from django.test import Client
from django.utils import timezone

from competition.answers import answer_digest
from competition.api import ApiProblem
from competition.clock import control_round
from competition.demo import demo_rules
from competition.models import (
    Completion,
    Incident,
    Mission,
    ResultProposal,
    ResultSnapshot,
    Round,
    SubmissionDecision,
    Team,
)
from competition.participant import round_eligible
from competition.results import approve_result, build_preview, manage_incident, propose_result
from competition.rules import approve_rules, mark_ready

pytestmark = pytest.mark.django_db


@pytest.fixture
def ended_hunt(settings):
    settings.PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]
    users = get_user_model()
    maker = users.objects.create_superuser(username="result-maker", password="test-only")
    reviewer = users.objects.create_superuser(username="result-reviewer", password="test-only")
    teams = [
        Team.objects.create(
            code=code,
            name=f"Synthetic {code}",
            member_count=3,
            is_demo=True,
            user=users.objects.create_user(username=code, password="test-only"),
        )
        for code in ["TEAM-A", "TEAM-B"]
    ]
    owners = {
        key: maker.pk
        for key in ["technical_lead", "content_lead", "operations_lead", "adjudicator"]
    }
    owners["verifier"] = reviewer.pk
    round = Round.objects.create(
        number=1,
        title="Synthetic results",
        is_demo=True,
        delivery_mode="ONLINE_HUNT",
        rules_version="v1",
        rules={
            **demo_rules(1),
            "answer_format": "four_ascii_digits",
            "expected_mission_count": 2,  # Historical two-mission results fixture.
        },
        owners=owners,
        advancement_count=1,
        active_budget_ms=60_000,
    )
    missions = []
    for code in ["M1", "M2"]:
        mission = Mission.objects.create(
            round=round,
            public_id=code,
            hint="Synthetic",
            keyword=code,
            qr_location="Fictional",
            clue_location="Fictional",
            volunteer_owner=maker,
            prepared_by=maker,
            verified_by=reviewer,
            verified_at=timezone.now(),
        )
        mission.answer_verifiers = [
            {"version": "v1", "digest": answer_digest(mission.pk, "v1", "0042")}
        ]
        mission.save()
        mission.verified_by = reviewer
        mission.verified_at = timezone.now()
        mission.save(update_fields=["verified_by", "verified_at"])
        missions.append(mission)
    approve_rules(round.pk, reviewer)
    mark_ready(round.pk, maker)
    start = timezone.now() - timedelta(minutes=2)
    for action, second in [("open_lobby", 0), ("start", 0), ("end", 30)]:
        round.refresh_from_db()
        with patch(
            "competition.clock.database_now", return_value=start + timedelta(seconds=second)
        ):
            control_round(
                round.pk,
                maker,
                {
                    "action": action,
                    "action_id": str(uuid.uuid4()),
                    "expected_version": round.control_version,
                    "reason": "Synthetic clock evidence",
                },
            )
    round.refresh_from_db()
    return round, missions, teams, maker, reviewer, start


def completion(hunt, team_index=0, mission_index=0, elapsed=10_000):
    round, missions, teams, _, _, start = hunt
    mission, team = missions[mission_index], teams[team_index]
    when = start + timedelta(milliseconds=elapsed)
    identifier = uuid.uuid4()
    receipt = Signer(salt="competition.accepted-receipt.v1").sign_object(
        {
            "decision_id": str(identifier),
            "team_code": team.code,
            "active_elapsed_ms": elapsed,
            "outcome": "accepted",
        }
    )
    decision = SubmissionDecision.objects.create(
        id=identifier,
        team=team,
        round=round,
        mission=mission,
        idempotency_key=uuid.uuid4(),
        request_fingerprint="f" * 64,
        answer_hmac=mission.answer_verifiers[0]["digest"],
        answer_key_version="v1",
        ingress_at=when,
        admitted_at=when,
        active_elapsed_ms=elapsed,
        rules_version="v1",
        outcome="accepted",
        response_snapshot={"receipt": receipt, "outcome": "accepted"},
    )
    return Completion.objects.create(
        team=team,
        mission=mission,
        source_decision=decision,
        effective_at=when,
        effective_active_ms=elapsed,
    )


def proposal(hunt, status="PROVISIONAL", now=None, **extra):
    round, _, _, maker, _, _ = hunt
    round.refresh_from_db()
    current = now or timezone.now()
    preview = build_preview(round, current)
    data = {
        "action": "propose",
        "status": status,
        "action_id": str(uuid.uuid4()),
        "expected_version": round.control_version,
        "evidence_digest": preview["evidence_digest"],
        "reason": "Reviewed synthetic results",
        "evidence_confirmed": True,
        **extra,
    }
    with patch("competition.results.database_now", return_value=current):
        return propose_result(round.pk, maker, data)


def approve(hunt, proposed, now=None, actor=None, **extra):
    round, _, _, _, reviewer, _ = hunt
    with (
        patch("competition.results.database_now", return_value=now)
        if now is not None
        else nullcontext()
    ):
        return approve_result(
            round.pk,
            actor or reviewer,
            {
                "action": "approve",
                "proposal_id": proposed["proposal_id"],
                "action_id": str(uuid.uuid4()),
                "reason": "Independently reviewed synthetic publication",
                "evidence_confirmed": True,
                **extra,
            },
        )


def publish_provisional(hunt):
    approve(hunt, proposal(hunt))
    return ResultSnapshot.objects.get(round=hunt[0])


def test_ranks_zero_score_ties_and_rebuilds_voided_denominator_and_time(ended_hunt):
    round, missions, _, _, _, _ = ended_hunt
    preview = build_preview(round, timezone.now())
    assert [row["rank"] for row in preview["entries"]] == [1, 1]
    assert [row["tie_time_ms"] for row in preview["entries"]] == [None, None]
    assert preview["cutoff_tie"] == ["TEAM-A", "TEAM-B"]
    completion(ended_hunt, elapsed=10_000)
    completion(ended_hunt, mission_index=1, elapsed=20_000)
    assert build_preview(round, timezone.now())["entries"][0]["tie_time_ms"] == 20_000
    Mission.objects.filter(pk=missions[1].pk).update(is_void=True)
    preview = build_preview(round, timezone.now())
    assert preview["entries"][0]["score"] == preview["max_score"] == 1
    assert preview["entries"][0]["tie_time_ms"] == 10_000


def test_two_person_publication_appeals_and_final_qualification(ended_hunt):
    round, _, teams, maker, _, _ = ended_hunt
    completion(ended_hunt)
    proposed = proposal(ended_hunt)
    with pytest.raises(ApiProblem, match="different"):
        approve(ended_hunt, proposed, actor=maker)
    first = approve(ended_hunt, proposed)
    assert first["qualifier_codes"] == []
    next_round = Round.objects.create(number=2, title="Next", is_demo=True)
    assert not round_eligible(teams[0], next_round)
    provisional = ResultSnapshot.objects.get(pk=first["snapshot_id"])
    with pytest.raises(ApiProblem, match="appeal window"):
        proposal(ended_hunt, "FINAL", now=provisional.appeal_deadline - timedelta(microseconds=1))
    at_deadline = provisional.appeal_deadline
    final = approve(ended_hunt, proposal(ended_hunt, "FINAL", now=at_deadline), now=at_deadline)
    assert final["qualifier_codes"] == ["TEAM-A"]
    assert round_eligible(teams[0], next_round)
    assert not round_eligible(teams[1], next_round)
    assert ResultSnapshot.objects.get(pk=final["snapshot_id"]).supersedes_id == provisional.pk
    round.refresh_from_db()
    assert round.state == "FINALIZED"
    with pytest.raises(ApiProblem):
        proposal(ended_hunt)
    assert ResultSnapshot.objects.get(pk=provisional.pk).qualifier_codes == []


def test_cutoff_tie_requires_bound_reviewed_reserve_clue_evidence(ended_hunt):
    provisional = publish_provisional(ended_hunt)
    now = provisional.appeal_deadline
    with pytest.raises(ApiProblem, match="reserve-clue"):
        proposal(ended_hunt, "FINAL", now=now)
    for order in [["TEAM-A"], ["TEAM-A", "TEAM-A"], ["TEAM-A", "UNKNOWN"]]:
        with pytest.raises(ApiProblem):
            proposal(
                ended_hunt,
                "FINAL",
                now=now,
                tie_order=order,
                tie_evidence=["reserve-sheet-1"],
                tie_reason="Synthetic reserve clue",
            )
    reviewed = proposal(
        ended_hunt,
        "FINAL",
        now=now,
        tie_order=["TEAM-B", "TEAM-A"],
        tie_evidence=["reserve-sheet-1"],
        tie_reason="TEAM-B solved the supervised reserve clue first.",
    )
    result = approve(ended_hunt, reviewed, now=now)
    assert result["qualifier_codes"] == ["TEAM-B"]
    assert [
        row["rank"] for row in ResultSnapshot.objects.get(pk=result["snapshot_id"]).ranked_entries
    ] == [1, 1]


def test_material_incident_blocks_final_and_requires_independent_closure(ended_hunt):
    round, _, _, maker, reviewer, _ = ended_hunt
    completion(ended_hunt)
    incident = manage_incident(
        round.pk,
        maker,
        {
            "action": "open",
            "action_id": str(uuid.uuid4()),
            "reason": "Check evidence coverage",
            "category": "EVIDENCE_GAP",
            "material": True,
        },
    )
    provisional = publish_provisional(ended_hunt)
    with pytest.raises(ApiProblem, match="material incident"):
        proposal(ended_hunt, "FINAL", now=provisional.appeal_deadline)
    close = {
        "action": "close",
        "action_id": str(uuid.uuid4()),
        "reason": "Verified evidence coverage against receipts",
        "incident_id": incident["incident_id"],
        "evidence_refs": ["reconciliation-sheet-1"],
    }
    with pytest.raises(ApiProblem, match="different"):
        manage_incident(round.pk, maker, close)
    manage_incident(round.pk, reviewer, close)
    assert Incident.objects.get().closed_at is not None
    approve(
        ended_hunt,
        proposal(ended_hunt, "FINAL", now=provisional.appeal_deadline),
        now=provisional.appeal_deadline,
    )


@pytest.mark.parametrize("fault", ["missing_projection", "time", "receipt", "rules"])
def test_evidence_gaps_block_publication(ended_hunt, fault):
    round = ended_hunt[0]
    item = completion(ended_hunt)
    if fault == "missing_projection":
        Completion.objects.filter(pk=item.pk).delete()
    elif fault == "time":
        Completion.objects.filter(pk=item.pk).update(effective_active_ms=999)
    elif fault == "receipt":
        SubmissionDecision.objects.filter(pk=item.source_decision_id).update(response_snapshot={})
    else:
        Round.objects.filter(pk=round.pk).update(rules_digest="a" * 64)
    with pytest.raises(ApiProblem, match="evidence|receipt|snapshot|completion"):
        proposal(ended_hunt)
    assert ResultSnapshot.objects.count() == 0


def test_stale_evidence_rejects_approval_and_revision_resets_appeal(ended_hunt):
    round, missions, _, _, _, _ = ended_hunt
    completion(ended_hunt)
    proposed = proposal(ended_hunt)
    Mission.objects.filter(pk=missions[1].pk).update(is_void=True)
    with pytest.raises(ApiProblem, match="Evidence changed"):
        approve(ended_hunt, proposed)
    first = publish_provisional(ended_hunt)
    later = first.published_at + timedelta(minutes=3)
    second = approve(ended_hunt, proposal(ended_hunt, now=later), now=later)
    snapshot = ResultSnapshot.objects.get(pk=second["snapshot_id"])
    assert snapshot.revision == 2 and snapshot.supersedes_id == first.pk
    assert snapshot.appeal_deadline > first.appeal_deadline
    assert ResultProposal.objects.count() == 3


def test_publication_replay_conflict_permissions_and_reviewer_attestation(ended_hunt):
    round, _, teams, maker, reviewer, _ = ended_hunt
    completion(ended_hunt)
    with pytest.raises(PermissionDenied):
        propose_result(round.pk, teams[0].user, {})
    proposed = proposal(ended_hunt)
    data = {
        "action_id": str(uuid.uuid4()),
        "proposal_id": proposed["proposal_id"],
        "reason": "Reviewed once",
        "evidence_confirmed": True,
    }
    original = approve_result(round.pk, reviewer, data)
    assert approve_result(round.pk, reviewer, data) == original
    with pytest.raises(ApiProblem, match="differently"):
        approve_result(round.pk, reviewer, {**data, "reason": "Changed"})
    provisional = ResultSnapshot.objects.get(pk=original["snapshot_id"])
    final = proposal(ended_hunt, "FINAL", now=provisional.appeal_deadline)
    with pytest.raises(ApiProblem, match="Independently confirm"):
        approve(ended_hunt, final, now=provisional.appeal_deadline, evidence_confirmed=False)
    assert maker.pk != reviewer.pk


def test_new_attempt_cannot_inherit_old_final_qualifiers(ended_hunt):
    completion(ended_hunt)
    provisional = publish_provisional(ended_hunt)
    approve(
        ended_hunt,
        proposal(ended_hunt, "FINAL", now=provisional.appeal_deadline),
        now=provisional.appeal_deadline,
    )
    next_round = Round.objects.create(number=2, title="Next", is_demo=True)
    assert round_eligible(ended_hunt[2][0], next_round)
    client = Client()
    assert (
        client.post(
            "/api/auth/login",
            {"team_code": "TEAM-A", "password": "test-only"},
            content_type="application/json",
        ).status_code
        == 200
    )
    assert client.get(f"/api/rounds/{ended_hunt[0].pk}/results").json()["current_attempt"]
    Round.objects.create(number=1, attempt_no=2, title="Rerun", is_demo=True)
    assert not round_eligible(ended_hunt[2][0], next_round)
    assert not client.get(f"/api/rounds/{ended_hunt[0].pk}/results").json()["current_attempt"]


def test_qualified_team_cannot_use_native_scoring_in_an_external_round(ended_hunt):
    completion(ended_hunt)
    first = publish_provisional(ended_hunt)
    approve(
        ended_hunt,
        proposal(ended_hunt, "FINAL", now=first.appeal_deadline),
        now=first.appeal_deadline,
    )
    next_round = Round.objects.create(
        number=2, title="External quiz", is_demo=True, delivery_mode="EXTERNAL"
    )
    mission = Mission.objects.create(
        round=next_round,
        public_id="EXTERNAL-M1",
        hint="External material",
        keyword="NONE",
        qr_location="Fictional",
        clue_location="Fictional",
    )
    now = timezone.now()
    Round.objects.filter(pk=next_round.pk).update(
        state="LIVE",
        live_started_at=now,
        phase_started_at=now,
        deadline_at=now + timedelta(minutes=2),
        rules_version="external-v1",
        rules_snapshot={"rules": {"score_schema": {"score": "number"}}},
    )
    assert round_eligible(ended_hunt[2][0], next_round)
    client = Client()
    assert (
        client.post(
            "/api/auth/login",
            {"team_code": "TEAM-A", "password": "test-only"},
            content_type="application/json",
        ).status_code
        == 200
    )
    opened = client.post(
        "/api/missions/open", {"token": mission.token}, content_type="application/json"
    )
    assert opened.status_code == 409 and opened.json()["error"]["code"] == "external_delivery"
    response = client.post(
        f"/api/missions/{mission.token}/submit",
        {"answer": "0042"},
        content_type="application/json",
        HTTP_IDEMPOTENCY_KEY=str(uuid.uuid4()),
    )
    assert response.json()["outcome"] == "external_delivery"
    assert response.json()["points_awarded"] == 0
    assert Completion.objects.filter(mission=mission).count() == 0


def test_participants_see_published_snapshots_only_and_staff_writes_require_csrf(ended_hunt):
    round, _, teams, maker, _, _ = ended_hunt
    client = Client(enforce_csrf_checks=True)
    csrf = client.get("/api/auth/csrf").json()["csrf_token"]
    login = client.post(
        "/api/auth/login",
        {"team_code": teams[0].code, "password": "test-only"},
        content_type="application/json",
        HTTP_X_CSRFTOKEN=csrf,
    )
    assert login.status_code == 200
    assert client.get(f"/api/rounds/{round.pk}/results").json()["snapshot"] is None
    assert client.get(f"/api/staff/rounds/{round.pk}/results").status_code == 403
    completion(ended_hunt)
    proposed = proposal(ended_hunt)
    assert client.get(f"/api/rounds/{round.pk}/results").json()["history"] == []
    approve(ended_hunt, proposed)
    response = client.get(f"/api/rounds/{round.pk}/results").json()
    assert response["snapshot"]["status"] == "PROVISIONAL"
    assert "proposals" not in response and "answer_hmac" not in str(response)
    staff = Client(enforce_csrf_checks=True)
    staff.force_login(maker)
    assert (
        staff.post(
            f"/api/staff/rounds/{round.pk}/publish", {}, content_type="application/json"
        ).status_code
        == 403
    )


@pytest.mark.django_db(transaction=True)
def test_concurrent_approvals_publish_one_revision(ended_hunt):
    completion(ended_hunt)
    proposed = proposal(ended_hunt)
    barrier = Barrier(2)

    def worker():
        connections.close_all()
        try:
            barrier.wait(timeout=5)
            return approve(ended_hunt, proposed)["status"]
        except ApiProblem as error:
            return error.code
        finally:
            connections.close_all()

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(lambda _: worker(), range(2))) == [
            "PROVISIONAL",
            "already_published",
        ]
    assert ResultSnapshot.objects.count() == 1


@pytest.mark.django_db(transaction=True)
@pytest.mark.skipif(
    os.environ.get("TTH_BROWSER_INTEGRATION") != "1",
    reason="Opt-in: requires Vite and Playwright Chromium.",
)
def test_browser_provisional_to_final_qualification(ended_hunt, live_server):
    completion(ended_hunt)
    round = ended_hunt[0]
    Round.objects.create(number=2, title="Synthetic next round", is_demo=True)
    from competition.clock import database_now

    def rehearsal_clock():
        now = database_now()
        snapshot = ResultSnapshot.objects.filter(round=round).order_by("-revision").first()
        if snapshot:
            # Only this isolated test advances time; no endpoint accepts a phone clock.
            target = (
                snapshot.appeal_deadline
                if snapshot.status == "PROVISIONAL"
                else snapshot.published_at
            )
            return max(now, target + timedelta(seconds=1))
        return now

    node = shutil.which("node")
    assert node is not None
    with (
        patch("competition.results.database_now", side_effect=rehearsal_clock),
        patch("competition.results_views.database_now", side_effect=rehearsal_clock),
    ):
        result = subprocess.run(
            [node, "frontend/scripts/live-results-smoke.mjs"],
            cwd=Path(__file__).resolve().parents[2],
            env={
                **os.environ,
                "TTH_BACKEND_URL": live_server.url.replace("localhost", "127.0.0.1"),
                "TTH_RESULTS_ROUND": str(round.pk),
            },
            capture_output=True,
            text=True,
            timeout=60,
        )
    assert result.returncode == 0, result.stdout + result.stderr
    assert list(
        ResultSnapshot.objects.filter(round=round)
        .order_by("revision")
        .values_list("status", flat=True)
    ) == ["PROVISIONAL", "FINAL"]
