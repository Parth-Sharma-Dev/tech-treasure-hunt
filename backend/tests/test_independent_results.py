import uuid
from datetime import timedelta
from unittest.mock import patch

import pytest
from django.contrib.auth import get_user_model
from django.utils import timezone
from test_gameplay import login, open_mission, submit

from competition.answers import POOL_FORMAT
from competition.clock import control_round
from competition.demo import demo_rules
from competition.evidence import approve_recovery, make_bundle, propose_recovery, read_bundle
from competition.models import (
    Completion,
    EventContentSource,
    HuntCode,
    Mission,
    ResultSnapshot,
    Round,
    Team,
)
from competition.portal import earned_keywords
from competition.results import approve_result, build_preview, propose_result
from competition.rules import approve_rules, mark_ready

pytestmark = pytest.mark.django_db


@pytest.fixture
def ended_pool(settings):
    settings.PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]
    users = get_user_model()
    maker = users.objects.create_superuser(username="pool-maker")
    reviewer = users.objects.create_superuser(username="pool-reviewer")
    teams = [
        Team.objects.create(
            code=code,
            name=code,
            member_count=3,
            user=users.objects.create_user(username=code, password="test-only"),
        )
        for code in ["TEST-01", "TEST-02"]
    ]
    rules = {
        **demo_rules(1),
        "code_mode": "independent_pool",
        "max_code_claims": 3,
        "points_per_code": 1,
        "expected_code_count": 6,
        "expected_mission_count": 1,
        "answer_format": POOL_FORMAT,
    }
    owners = {
        role: maker.pk
        for role in ["technical_lead", "content_lead", "operations_lead", "adjudicator"]
    }
    owners["verifier"] = reviewer.pk
    round = Round.objects.create(
        number=1,
        title="Independent hunt",
        delivery_mode="ONLINE_HUNT",
        rules=rules,
        rules_version="hunt-pool-v1",
        owners=owners,
        advancement_count=1,
        active_budget_ms=120_000,
    )
    mission = Mission.objects.create(
        round=round,
        public_id="CLUE-1",
        hint="Find a location.",
        keyword="",
        qr_location="QR stand",
        clue_location="Private destination",
        prepared_by=maker,
        volunteer_owner=maker,
        verified_by=reviewer,
        verified_at=timezone.now(),
    )
    source = EventContentSource.objects.create(
        round=round,
        kind="CODE_POOL",
        filename="synthetic.csv",
        sha256="b" * 64,
        original_bytes=b"synthetic original",
        prepared_by=maker,
    )
    codes = [
        HuntCode.objects.create(round=round, source=source, code=f"!Ab{n}@x", keyword=f"WORD{n}")
        for n in range(6)
    ]
    approve_rules(round.pk, reviewer)
    mark_ready(round.pk, maker)
    start = timezone.now() - timedelta(seconds=40)
    for action, second in [("open_lobby", 0), ("start", 0)]:
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
                    "reason": "Synthetic acceptance",
                },
            )
    clients = [login(team.code) for team in teams]
    with patch("competition.gameplay.database_now", return_value=start + timedelta(seconds=1)):
        for client in clients:
            open_mission(client, mission)
    for client, selected, times in [
        (clients[0], codes[:3], [10, 20, 30]),
        (clients[1], codes[3:], [5, 15, 25]),
    ]:
        for code, second in zip(selected, times, strict=True):
            assert (
                submit(client, mission, code.code, now=start + timedelta(seconds=second)).json()[
                    "outcome"
                ]
                == "accepted"
            )
    round.refresh_from_db()
    with patch("competition.clock.database_now", return_value=start + timedelta(seconds=40)):
        control_round(
            round.pk,
            maker,
            {
                "action": "end",
                "action_id": str(uuid.uuid4()),
                "expected_version": round.control_version,
                "reason": "Synthetic acceptance end",
            },
        )
    round.refresh_from_db()
    return round, mission, teams, maker, reviewer, codes


def test_three_code_standings_keyword_portal_and_reviewed_qualification(ended_pool):
    round, mission, teams, maker, reviewer, _ = ended_pool
    now = timezone.now()
    preview = build_preview(round, now)
    assert preview["evidence_gaps"] == preview["configuration_errors"] == []
    assert preview["max_score"] == 3
    assert [e["team_code"] for e in preview["entries"]] == [teams[1].code, teams[0].code]
    assert [e["tie_time_ms"] for e in preview["entries"]] == [25000, 30000]
    assert earned_keywords(teams[0]) == ["WORD0", "WORD1", "WORD2"]
    Mission.objects.filter(pk=mission.pk).update(is_void=True)
    assert build_preview(round, now)["entries"] == preview["entries"]
    proposal = propose_result(
        round.pk,
        maker,
        {
            "action_id": str(uuid.uuid4()),
            "expected_version": round.control_version,
            "evidence_digest": build_preview(round, now)["evidence_digest"],
            "status": "PROVISIONAL",
            "public_summary": "Synthetic provisional",
            "reason": "Verified independent claims",
        },
    )
    approve_result(
        round.pk,
        reviewer,
        {
            "action_id": str(uuid.uuid4()),
            "proposal_id": proposal["proposal_id"],
            "reason": "Independent verification",
            "evidence_confirmed": True,
        },
    )
    round.refresh_from_db()
    final_now = ResultSnapshot.objects.get(round=round).appeal_deadline + timedelta(seconds=1)
    with patch("competition.results.database_now", return_value=final_now):
        proposal = propose_result(
            round.pk,
            maker,
            {
                "action_id": str(uuid.uuid4()),
                "expected_version": round.control_version,
                "evidence_digest": build_preview(round, final_now)["evidence_digest"],
                "status": "FINAL",
                "evidence_confirmed": True,
                "reason": "Independent code evidence and appeal window reviewed",
            },
        )
        approve_result(
            round.pk,
            reviewer,
            {
                "action_id": str(uuid.uuid4()),
                "proposal_id": proposal["proposal_id"],
                "reason": "Verified final qualification",
                "evidence_confirmed": True,
            },
        )
    assert ResultSnapshot.objects.filter(round=round, status="FINAL").get().qualifier_codes == [
        teams[1].code
    ]


def test_signed_restore_recovers_pool_keywords_and_exclusive_claims(ended_pool):
    round, _, _, maker, reviewer, codes = ended_pool
    baseline = build_preview(round, timezone.now())["entries"]
    bundle = make_bundle(round)["signed_bundle"]
    payload = read_bundle(bundle, round)
    assert any(o["model"] == "competition.huntcode" for o in payload["objects"])
    assert any(o["model"] == "competition.eventcontentsource" for o in payload["objects"])
    Completion.objects.all().delete()
    HuntCode.objects.all()._raw_delete("default")
    EventContentSource.objects.all()._raw_delete("default")
    proposed = propose_recovery(
        round.pk,
        maker,
        {
            "action_id": str(uuid.uuid4()),
            "expected_version": round.control_version,
            "signed_bundle": bundle,
            "reason": "Synthetic pool restore",
            "evidence_refs": ["synthetic-retained-original"],
        },
    )
    approve_recovery(
        round.pk,
        reviewer,
        {
            "action_id": str(uuid.uuid4()),
            "proposal_id": proposed["recovery_proposal_id"],
            "reason": "Independent restored evidence",
            "evidence_confirmed": True,
        },
    )
    assert Completion.objects.count() == HuntCode.objects.count() == 6
    assert list(HuntCode.objects.order_by("pk").values_list("keyword", flat=True)) == [
        c.keyword for c in codes
    ]
    preview = build_preview(round, timezone.now())
    assert preview["entries"] == baseline and preview["evidence_gaps"] == []
