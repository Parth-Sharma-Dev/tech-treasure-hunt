import uuid
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest
from django.contrib.auth import get_user_model
from django.db import connections
from test_gameplay import game as _game
from test_gameplay import login, open_mission, submit

from competition.answers import POOL_FORMAT
from competition.models import Completion, EventContentSource, HuntCode, Round, Team

pytestmark = pytest.mark.django_db
game = _game


def pool_game(game):
    round, missions, team, actor, client = game
    Round.objects.filter(pk=round.pk).update(state="DRAFT")
    source = EventContentSource.objects.create(
        round=round,
        kind="CODE_POOL",
        filename="synthetic.csv",
        sha256="a" * 64,
        original_bytes=b"synthetic",
        prepared_by=actor,
    )
    codes = []
    for code, word in zip(
        ["!Ab3@x", "X,y;Z!", "T3$xx?", "Z4*yy!"], ["Python", "List", "C", "Loop"], strict=True
    ):
        codes.append(HuntCode.objects.create(round=round, source=source, code=code, keyword=word))
    rules = {
        **round.rules_snapshot["rules"],
        "answer_format": POOL_FORMAT,
        "code_mode": "independent_pool",
        "max_code_claims": 3,
    }
    Round.objects.filter(pk=round.pk).update(state="LIVE", rules_snapshot={"rules": rules})
    round.refresh_from_db()
    open_mission(client, missions[0])
    return round, missions, team, actor, client, codes


def other_team():
    user = get_user_model().objects.create_user(username="other-pool", password="test-only")
    return Team.objects.create(code="POOL-02", name="Other pool team", member_count=3, user=user)


def test_any_mission_three_successes_punctuation_keyword_and_replay(game):
    round, missions, team, _, client, codes = pool_game(game)
    key = uuid.uuid4()
    first = submit(client, missions[0], codes[0].code.lower(), key).json()
    assert first["outcome"] == "accepted" and first["keyword"] == "Python"
    assert (
        submit(client, missions[0], codes[0].code.upper(), key).json()["receipt"]
        == first["receipt"]
    )
    assert submit(client, missions[0], codes[0].code).json()["outcome"] == "already_claimed_by_you"
    assert submit(client, missions[0], "!wrong").json()["outcome"] == "incorrect"
    for code in codes[1:3]:
        assert submit(client, missions[0], code.code).json()["outcome"] == "accepted"
    assert submit(client, missions[0], codes[3].code).json()["outcome"] == "claim_limit_reached"
    state = client.get(f"/api/rounds/{round.pk}/state").json()
    assert state["score"] == state["max_score"] == 3
    assert [c["keyword"] for c in state["completions"]] == ["Python", "List", "C"]
    assert Completion.objects.filter(team=team).count() == 3
    page = client.get(f"/api/missions/{missions[0].token}").json()
    assert not page["completed"] and page["successful_claims"] == 3
    assert "code" not in page and "clue_location" not in page
    other_team()
    other = login("POOL-02")
    open_mission(other, missions[1])
    refused = submit(other, missions[1], codes[0].code).json()
    assert refused["outcome"] == "code_already_claimed" and refused["keyword"] is None
    assert submit(other, missions[1], codes[3].code).json()["outcome"] == "accepted"
    Round.objects.filter(pk=round.pk).update(state="FROZEN")
    assert submit(client, missions[0], codes[0].code, key).json()["receipt"] == first["receipt"]
    assert submit(other, missions[1], "!wrong").json()["outcome"] == "paused"


@pytest.mark.django_db(transaction=True)
def test_simultaneous_teams_claim_same_code_once(game):
    _, missions, _, _, client, codes = pool_game(game)
    other_team()
    other = login("POOL-02")
    open_mission(other, missions[1])
    barrier = Barrier(2)

    def press(client, mission):
        try:
            barrier.wait(timeout=10)
            return submit(client, mission, codes[0].code).json()["outcome"]
        finally:
            connections.close_all()

    with ThreadPoolExecutor(max_workers=2) as workers:
        futures = [
            workers.submit(press, client, missions[0]),
            workers.submit(press, other, missions[1]),
        ]
        assert sorted(f.result(timeout=20) for f in futures) == ["accepted", "code_already_claimed"]
    assert Completion.objects.count() == 1


@pytest.mark.django_db(transaction=True)
def test_concurrent_distinct_codes_cannot_exceed_team_cap(game):
    _, missions, _, _, client, codes = pool_game(game)
    for code in codes[:2]:
        assert submit(client, missions[0], code.code).json()["outcome"] == "accepted"
    barrier = Barrier(2)

    def press(code):
        try:
            barrier.wait(timeout=10)
            return submit(client, missions[0], code.code).json()["outcome"]
        finally:
            connections.close_all()

    with ThreadPoolExecutor(max_workers=2) as workers:
        futures = [workers.submit(press, code) for code in codes[2:]]
        assert sorted(f.result(timeout=20) for f in futures) == ["accepted", "claim_limit_reached"]
    assert Completion.objects.count() == 3
