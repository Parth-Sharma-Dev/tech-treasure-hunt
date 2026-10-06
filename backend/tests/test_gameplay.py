import uuid
from concurrent.futures import ThreadPoolExecutor, TimeoutError
from datetime import timedelta
from threading import Barrier, Event
from unittest.mock import patch

import pytest
from django.contrib.auth import get_user_model
from django.core.signing import BadSignature, Signer
from django.db import connections, transaction
from django.test import Client
from django.utils import timezone

from competition.answers import answer_digest
from competition.clock import control_round
from competition.gameplay import shared_round
from competition.models import (
    AttemptState,
    Completion,
    Mission,
    Round,
    SubmissionDecision,
    Team,
    Visit,
)

pytestmark = pytest.mark.django_db


def post(client, path, data, key=None):
    csrf = client.get("/api/auth/csrf").json()["csrf_token"]
    headers = {"HTTP_X_CSRFTOKEN": csrf}
    if key:
        headers["HTTP_IDEMPOTENCY_KEY"] = str(key)
    return client.post(path, data, content_type="application/json", **headers)


def login(code="TEST-01"):
    client = Client(enforce_csrf_checks=True)
    assert (
        post(client, "/api/auth/login", {"team_code": code, "password": "test-only"}).status_code
        == 200
    )
    return client


@pytest.fixture
def game(settings):
    settings.PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]
    actor = get_user_model().objects.create_superuser(username="game-controller", password=None)
    user = get_user_model().objects.create_user(username="team-internal", password="test-only")
    team = Team.objects.create(code="TEST-01", name="Synthetic team", user=user, member_count=3)
    start = timezone.now()
    round = Round.objects.create(
        number=1, title="Synthetic hunt", delivery_mode="ONLINE_HUNT", active_budget_ms=120_000
    )
    missions = []
    for number in range(2):
        mission = Mission.objects.create(
            round=round,
            public_id=f"M{number}",
            hint="Synthetic hint",
            keyword=f"WORD{number}",
            qr_location="Fictional QR",
            clue_location="Fictional clue",
        )
        mission.answer_verifiers = [
            {"version": "v1", "digest": answer_digest(mission.pk, "v1", "0042")}
        ]
        mission.save()
        missions.append(mission)
    rules = {
        "team_answer_limit": 10,
        "team_answer_window_ms": 60_000,
        "free_wrong_attempts": 5,
        "cooldown_seconds": [30, 60, 120, 240, 300],
    }
    Round.objects.filter(pk=round.pk).update(
        state="LIVE",
        phase_started_at=start,
        live_started_at=start,
        deadline_at=start + timedelta(seconds=120),
        rules_version="v1",
        rules_snapshot={"rules": rules},
    )
    round.refresh_from_db()
    return round, missions, team, actor, login()


def submit(client, mission, answer="0042", key=None, now=None):
    if now is not None:
        with patch("competition.gameplay.database_now", return_value=now):
            return post(
                client,
                f"/api/missions/{mission.token}/submit",
                {"answer": answer},
                key or uuid.uuid4(),
            )
    else:
        return post(
            client, f"/api/missions/{mission.token}/submit", {"answer": answer}, key or uuid.uuid4()
        )


def open_mission(client, mission):
    response = post(client, "/api/missions/open", {"token": mission.token})
    assert response.status_code == 200
    return response.json()


def test_get_does_not_open_and_fallback_reveals_only_own_clue(game):
    round, missions, _, _, client = game
    mission = missions[0]
    assert client.get(f"/api/missions/{mission.token}").json()["hint"] is None
    assert Visit.objects.count() == 0
    response = post(client, "/api/missions/open", {"fallback_code": mission.fallback_code.lower()})
    assert response.json()["hint"] == "Synthetic hint"
    assert Visit.objects.get().access_method == "FALLBACK"
    assert "answer_verifiers" not in response.json()
    assert client.get(f"/api/missions/{missions[1].token}").json()["hint"] is None
    get_user_model().objects.create_user(username="other-internal", password="test-only")
    Team.objects.create(
        code="OTHER",
        name="Other team",
        member_count=3,
        user=get_user_model().objects.get(username="other-internal"),
    )
    other = login("OTHER")
    assert other.get(f"/api/missions/{mission.token}").json()["hint"] is None
    assert other.get(f"/api/rounds/{round.pk}/state").json()["score"] == 0


def test_correct_answer_receipt_replay_and_effective_score_are_separate(game):
    round, missions, team, actor, client = game
    mission = missions[0]
    open_mission(client, mission)
    key = uuid.uuid4()
    accepted = submit(client, mission, key=key).json()
    assert accepted["outcome"] == "accepted" and accepted["keyword"] == "WORD0"
    assert Completion.objects.count() == 1
    decoded = Signer(salt="competition.accepted-receipt.v1").unsign_object(accepted["receipt"])
    assert decoded["team_code"] == team.code and decoded["decision_id"] == accepted["decision_id"]
    with pytest.raises(BadSignature):
        Signer(salt="competition.accepted-receipt.v1").unsign_object(accepted["receipt"] + "x")
    assert client.get(f"/api/rounds/{round.pk}/state").json()["score"] == 1
    control_round(
        round.pk,
        actor,
        {
            "action": "freeze",
            "expected_version": 0,
            "action_id": str(uuid.uuid4()),
            "reason": "Replay test",
        },
    )
    Mission.objects.filter(pk=mission.pk).update(is_void=True)
    replayed = submit(client, mission, key=key).json()
    assert {key: value for key, value in replayed.items() if key != "request_id"} == {
        key: value for key, value in accepted.items() if key != "request_id"
    }
    assert client.get(f"/api/rounds/{round.pk}/state").json()["score"] == 0
    assert client.get("/api/me/receipts").json()["receipts"][0]["receipt"] == accepted["receipt"]
    assert client.get(f"/api/rounds/{round.pk}/attempts/{key}").json()["status"] == "recorded"
    assert (
        client.get(f"/api/rounds/{round.pk}/attempts/{uuid.uuid4()}").json()["status"] == "unknown"
    )
    assert submit(client, mission, answer="0000", key=key).status_code == 409
    assert submit(client, missions[1], key=key).status_code == 409


@pytest.mark.parametrize(
    "state,outcome", [("LOBBY", "round_closed"), ("FROZEN", "paused"), ("ENDED", "round_closed")]
)
def test_non_live_attempt_rejection_is_durable(game, state, outcome):
    round, missions, _, _, client = game
    Round.objects.filter(pk=round.pk).update(state=state)
    key = uuid.uuid4()
    assert submit(client, missions[0], key=key).json()["outcome"] == outcome
    Round.objects.filter(pk=round.pk).update(state="LIVE")
    assert submit(client, missions[0], key=key).json()["outcome"] == outcome
    assert Completion.objects.count() == AttemptState.objects.count() == 0


@pytest.mark.parametrize("offset,outcome", [(-1, "accepted"), (0, "accepted"), (1, "late")])
def test_admission_cutoff_boundary(game, offset, outcome):
    round, missions, _, _, client = game
    open_mission(client, missions[0])
    response = submit(client, missions[0], now=round.deadline_at + timedelta(microseconds=offset))
    assert response.json()["outcome"] == outcome


def test_malformed_unopened_and_csrf_requests_cannot_score(game):
    _, missions, _, _, client = game
    mission = missions[0]
    for answer in ["42", "٠٠٤٢", 42, "0042\n"]:
        assert submit(client, mission, answer=answer).status_code == 400
    assert SubmissionDecision.objects.count() == 0
    assert submit(client, mission).json()["outcome"] == "not_opened"
    assert (
        client.post(
            f"/api/missions/{mission.token}/submit",
            {"answer": "0042"},
            content_type="application/json",
        ).status_code
        == 403
    )
    assert Completion.objects.count() == 0


def test_cooldown_excludes_pause_and_only_evaluated_wrong_answers_count(game):
    round, missions, _, actor, client = game
    mission = missions[0]
    open_mission(client, mission)
    start = round.live_started_at
    for number in range(6):
        result = submit(client, mission, answer="0000", now=start + timedelta(seconds=1)).json()
        assert result["wrong_count"] == number + 1
    assert result["cooldown_remaining_ms"] == 30_000
    with patch("competition.clock.database_now", return_value=start + timedelta(seconds=5)):
        control_round(
            round.pk,
            actor,
            {
                "action": "freeze",
                "expected_version": 0,
                "action_id": str(uuid.uuid4()),
                "reason": "Pause cooldown",
            },
        )
    with patch("competition.clock.database_now", return_value=start + timedelta(seconds=1000)):
        control_round(
            round.pk,
            actor,
            {
                "action": "resume",
                "expected_version": 1,
                "action_id": str(uuid.uuid4()),
                "reason": "Resume cooldown",
            },
        )
    assert (
        submit(client, mission, now=start + timedelta(seconds=1000)).json()["outcome"] == "cooldown"
    )
    assert AttemptState.objects.get().evaluated_wrong_count == 6
    assert (
        submit(client, mission, now=start + timedelta(seconds=1027)).json()["outcome"] == "accepted"
    )


def test_quota_is_shared_across_missions_and_replay_does_not_consume_it(game):
    round, missions, _, _, client = game
    for mission in missions:
        open_mission(client, mission)
    now = round.live_started_at + timedelta(seconds=1)
    key = uuid.uuid4()
    teammate = login()
    for number in range(10):
        assert (
            submit(
                client if number % 2 == 0 else teammate,
                missions[number % 2],
                answer="0000",
                key=key if number == 0 else None,
                now=now,
            ).json()["outcome"]
            == "incorrect"
        )
    assert (
        submit(client, missions[0], answer="0000", key=key, now=now).json()["outcome"]
        == "incorrect"
    )
    assert submit(client, missions[1], now=now).json()["outcome"] == "throttled"
    assert sum(AttemptState.objects.values_list("evaluated_wrong_count", flat=True)) == 10
    assert (
        submit(client, missions[1], now=now + timedelta(seconds=60)).json()["outcome"] == "accepted"
    )


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize("same_key", [False, True])
def test_two_simultaneous_correct_answers_create_one_completion(game, same_key):
    _, missions, _, _, original = game
    mission = missions[0]
    open_mission(original, mission)
    barrier = Barrier(2)
    shared_key = uuid.uuid4() if same_key else None

    def worker():
        connections.close_all()
        try:
            client = Client()
            client.cookies = original.cookies.copy()
            barrier.wait(timeout=5)
            return submit(client, mission, key=shared_key).json()["outcome"]
        finally:
            connections.close_all()

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(lambda _: worker(), range(2))) == (
            ["accepted", "accepted"] if same_key else ["accepted", "already_completed"]
        )
    assert Completion.objects.count() == 1
    assert SubmissionDecision.objects.count() == (1 if same_key else 2)


@pytest.mark.django_db(transaction=True)
def test_lock_wait_does_not_reserve_admission_before_deadline(game):
    round, missions, team, _, client = game
    open_mission(client, missions[0])
    deadline = timezone.now() + timedelta(milliseconds=500)
    Round.objects.filter(pk=round.pk).update(deadline_at=deadline)
    acquired = Event()

    def notified_shared(round_id):
        result = shared_round(round_id)
        acquired.set()
        return result

    # Use the actual database clock here, rather than submit()'s fixed mock.
    def live_worker():
        connections.close_all()
        try:
            return post(
                client,
                f"/api/missions/{missions[0].token}/submit",
                {"answer": "0042"},
                uuid.uuid4(),
            ).json()
        finally:
            connections.close_all()

    with (
        ThreadPoolExecutor(max_workers=1) as pool,
        patch("competition.gameplay.shared_round", notified_shared),
    ):
        with transaction.atomic():
            Team.objects.select_for_update().get(pk=team.pk)
            result = pool.submit(live_worker)
            assert acquired.wait(timeout=3)
            Event().wait(max(0, (deadline - timezone.now()).total_seconds()) + 0.05)
        assert result.result(timeout=5)["outcome"] == "late"
    assert Completion.objects.count() == 0


@pytest.mark.django_db(transaction=True)
def test_freeze_waits_for_admitted_answer_to_commit(game):
    round, missions, _, actor, client = game
    open_mission(client, missions[0])
    admitted, release = Event(), Event()

    def blocked_digest(*args):
        admitted.set()
        assert release.wait(timeout=5)
        return answer_digest(*args)

    def answer_worker():
        connections.close_all()
        try:
            return post(
                client,
                f"/api/missions/{missions[0].token}/submit",
                {"answer": "0042"},
                uuid.uuid4(),
            ).json()
        finally:
            connections.close_all()

    def freeze_worker():
        connections.close_all()
        try:
            return control_round(
                round.pk,
                actor,
                {
                    "action": "freeze",
                    "expected_version": 0,
                    "action_id": str(uuid.uuid4()),
                    "reason": "Lock-order test",
                },
            )
        finally:
            connections.close_all()

    with (
        ThreadPoolExecutor(max_workers=2) as pool,
        patch("competition.gameplay.answer_digest", blocked_digest),
    ):
        answer = pool.submit(answer_worker)
        assert admitted.wait(timeout=3)
        frozen = pool.submit(freeze_worker)
        try:
            with pytest.raises(TimeoutError):
                frozen.result(timeout=0.15)
        finally:
            release.set()
        assert answer.result(timeout=5)["outcome"] == "accepted"
        assert frozen.result(timeout=5)["state"] == "FROZEN"
    assert submit(client, missions[1]).json()["outcome"] == "paused"
