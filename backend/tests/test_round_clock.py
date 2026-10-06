import json
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from threading import Barrier
from unittest.mock import patch

import pytest
from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied
from django.core.management import call_command
from django.db import connections
from django.test import Client
from django.utils import timezone

from competition.api import ApiProblem
from competition.clock import active_elapsed, clock_payload, control_round, database_now
from competition.models import AuditEvent, Round, RoundPhase

pytestmark = pytest.mark.django_db


@pytest.fixture
def clock_round():
    actor = get_user_model().objects.create_superuser(username="clock-controller", password=None)
    round = Round.objects.create(
        number=1, title="Synthetic clock test", state="READY", active_budget_ms=60_000, is_demo=True
    )
    return round, actor


def act(round, actor, action, now=None, **overrides):
    round.refresh_from_db()
    data = {
        "action": action,
        "action_id": str(uuid.uuid4()),
        "expected_version": round.control_version,
        "reason": "Synthetic test",
    }
    data.update(overrides)
    if now is None:
        return control_round(round.pk, actor, data)
    with patch("competition.clock.database_now", return_value=now):
        return control_round(round.pk, actor, data)


def test_pause_resume_excludes_frozen_time_and_preserves_phases(clock_round):
    round, actor = clock_round
    start = timezone.now()
    act(round, actor, "open_lobby", start)
    act(round, actor, "start", start)
    frozen = act(round, actor, "freeze", start + timedelta(seconds=10))
    assert frozen["remaining_ms"] == 50_000
    round.refresh_from_db()
    assert active_elapsed(round, start + timedelta(hours=2)) == 10_000
    resumed = act(round, actor, "resume", start + timedelta(seconds=40))
    assert resumed["deadline_at"] == (start + timedelta(seconds=90)).isoformat()
    ended = act(round, actor, "end", start + timedelta(seconds=50))
    assert ended["active_elapsed_ms"] == 20_000
    phases = list(RoundPhase.objects.order_by("pk"))
    assert [phase.phase_type for phase in phases] == ["LIVE", "FROZEN", "LIVE"]
    assert [phase.ended_at - phase.started_at for phase in phases] == [
        timedelta(seconds=10),
        timedelta(seconds=30),
        timedelta(seconds=10),
    ]
    assert AuditEvent.objects.filter(action="round_control").count() == 5


def test_extensions_change_only_budget_and_deadline_once(clock_round):
    round, actor = clock_round
    start = timezone.now()
    act(round, actor, "open_lobby", start)
    act(round, actor, "start", start)
    key = str(uuid.uuid4())
    response = act(
        round, actor, "extend", start + timedelta(seconds=5), action_id=key, extension_ms=30_000
    )
    assert response["active_budget_ms"] == 90_000
    assert (
        act(
            round,
            actor,
            "extend",
            start + timedelta(seconds=9),
            action_id=key,
            expected_version=2,
            extension_ms=30_000,
        )
        == response
    )
    act(round, actor, "freeze", start + timedelta(seconds=10))
    extended = act(round, actor, "extend", start + timedelta(seconds=20), extension_ms=20_000)
    assert extended["remaining_ms"] == 100_000
    resumed = act(round, actor, "resume", start + timedelta(seconds=40))
    assert resumed["deadline_at"] == (start + timedelta(seconds=140)).isoformat()


@pytest.mark.parametrize("action", ["freeze", "resume", "extend", "end"])
def test_delayed_control_closes_at_original_deadline(clock_round, action):
    round, actor = clock_round
    start = timezone.now()
    act(round, actor, "open_lobby", start)
    act(round, actor, "start", start)
    round.refresh_from_db()
    assert clock_payload(round, start + timedelta(seconds=61))["state"] == "ENDED"
    assert RoundPhase.objects.count() == 0  # Reads do not create evidence.
    response = act(
        round,
        actor,
        action,
        start + timedelta(minutes=5),
        **({"extension_ms": 30_000} if action == "extend" else {}),
    )
    assert response["state"] == "ENDED"
    assert response["deadline_reached"]
    assert response["active_budget_ms"] == response["active_elapsed_ms"] == 60_000
    assert RoundPhase.objects.get().ended_at == start + timedelta(seconds=60)
    with pytest.raises(ApiProblem, match="unavailable"):
        act(round, actor, "resume")


def test_action_replay_after_end_is_original_and_payload_conflict_fails(clock_round):
    round, actor = clock_round
    start = timezone.now()
    act(round, actor, "open_lobby", start)
    key = str(uuid.uuid4())
    original = act(round, actor, "start", start, action_id=key)
    act(round, actor, "end", start + timedelta(seconds=1))
    assert act(round, actor, "start", action_id=key, expected_version=1) == original
    with pytest.raises(ApiProblem, match="differently"):
        act(round, actor, "start", action_id=key, expected_version=1, reason="Changed")


@pytest.mark.parametrize(
    "state,action",
    [
        ("DRAFT", "start"),
        ("READY", "start"),
        ("LOBBY", "resume"),
        ("ENDED", "extend"),
        ("FINALIZED", "open_lobby"),
    ],
)
def test_invalid_transitions_do_not_create_evidence(clock_round, state, action):
    round, actor = clock_round
    Round.objects.filter(pk=round.pk).update(state=state)
    with pytest.raises(ApiProblem):
        act(round, actor, action, **({"extension_ms": 1} if action == "extend" else {}))
    assert AuditEvent.objects.count() == RoundPhase.objects.count() == 0


def test_permission_version_and_paper_mode_guards(clock_round):
    round, actor = clock_round
    participant = get_user_model().objects.create_user(username="clock-participant")
    with pytest.raises(PermissionDenied):
        act(round, participant, "open_lobby")
    with pytest.raises(ApiProblem, match="Refresh"):
        act(round, actor, "open_lobby", expected_version=99)
    Round.objects.filter(pk=round.pk).update(play_mode="PAPER")
    with pytest.raises(ApiProblem, match="paper"):
        act(round, actor, "open_lobby")


@pytest.mark.django_db(transaction=True)
def test_simultaneous_controls_apply_once_on_postgres(clock_round):
    round, actor = clock_round
    barrier = Barrier(2)

    def worker():
        connections.close_all()
        try:
            barrier.wait(timeout=5)
            return control_round(
                round.pk,
                actor,
                {
                    "action": "open_lobby",
                    "action_id": str(uuid.uuid4()),
                    "expected_version": 0,
                    "reason": "Concurrent control test",
                },
            )["state"]
        except ApiProblem as error:
            return error.code
        finally:
            connections.close_all()

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(lambda _: worker(), range(2))) == ["LOBBY", "stale_control"]
    assert AuditEvent.objects.count() == 1


def test_global_action_key_collision_rolls_back_round(clock_round):
    round, actor = clock_round
    key = str(uuid.uuid4())
    act(round, actor, "open_lobby", action_id=key)
    other = Round.objects.create(number=2, title="Other", state="READY")
    with pytest.raises(ApiProblem):
        act(other, actor, "open_lobby", action_id=key)
    other.refresh_from_db()
    assert other.state == "READY" and other.control_version == 0


def test_staff_api_csrf_and_private_access(clock_round):
    round, actor = clock_round
    client = Client(enforce_csrf_checks=True)
    assert client.get("/api/staff/rounds").status_code == 403
    client.force_login(actor)
    url = f"/api/staff/rounds/{round.pk}/control"
    payload = {
        "action": "open_lobby",
        "action_id": str(uuid.uuid4()),
        "reason": "API test",
        "expected_version": 0,
    }
    assert client.post(url, json.dumps(payload), content_type="application/json").status_code == 403
    csrf = client.get("/api/auth/csrf").json()["csrf_token"]
    assert (
        client.post(
            url, json.dumps(payload), content_type="application/json", HTTP_X_CSRFTOKEN=csrf
        ).status_code
        == 200
    )
    assert client.get("/api/staff/rounds").json()["rounds"][0]["state"] == "LOBBY"


def test_clock_is_database_time():
    assert abs((database_now() - timezone.now()).total_seconds()) < 5


def test_expiry_command_is_repeatable_and_caps_interval(clock_round):
    round, actor = clock_round
    start = timezone.now() - timedelta(minutes=2)
    act(round, actor, "open_lobby", start)
    act(round, actor, "start", start)
    call_command("end_expired_rounds", actor=actor.username)
    call_command("end_expired_rounds", actor=actor.username)
    round.refresh_from_db()
    assert round.state == "ENDED"
    assert round.accumulated_active_ms == 60_000
    assert RoundPhase.objects.count() == 1
    assert RoundPhase.objects.get().ended_at == start + timedelta(seconds=60)
