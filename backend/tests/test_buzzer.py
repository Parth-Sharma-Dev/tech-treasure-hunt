import uuid

import pytest
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import Client
from django.utils import timezone

from competition.buzzer import control_window, staff_desk
from competition.clock import control_round
from competition.demo import demo_rules
from competition.models import (
    BuzzerClosure,
    BuzzerPress,
    BuzzerQuestion,
    BuzzerWindow,
    Incident,
    ResultSnapshot,
    Round,
    Team,
)
from competition.portal import participant_overview
from competition.rules import approve_rules, mark_ready, readiness_errors

pytestmark = pytest.mark.django_db


@pytest.fixture
def buzzer(settings):
    settings.PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]
    users = get_user_model()
    maker = users.objects.create_superuser(username="buzzer-maker", password="test-only")
    reviewer = users.objects.create_superuser(username="buzzer-reviewer", password="test-only")
    teams = [
        Team.objects.create(
            code=f"BUZZ-{index}",
            name=f"Synthetic finalist {index}",
            member_count=3,
            is_demo=True,
            user=users.objects.create_user(username=f"buzz-{index}", password="test-only"),
        )
        for index in range(3)
    ]
    previous = Round.objects.create(
        number=4, title="Synthetic final qualification", is_demo=True, state="FINALIZED"
    )
    ResultSnapshot.objects.create(
        round=previous,
        revision=1,
        status="FINAL",
        maker=maker,
        approver=reviewer,
        qualifier_codes=[team.code for team in teams[:2]],
        published_at=timezone.now(),
    )
    round = Round.objects.create(
        number=5,
        title="Synthetic buzzer final",
        is_demo=True,
        delivery_mode="BUZZER",
        active_budget_ms=60000,
        rules_version="buzzer-v1",
        rules={
            **demo_rules(5),
            "buzzer_order_policy": "database_receipt_time",
            "buzzer_latency_policy": "no_compensation",
            "buzzer_equal_time_policy": "staff_review_required",
            "buzzer_early_policy": "reject_closed_window",
            "offline_rules_reference": "synthetic-host-rules",
        },
        owners={
            **{
                role: maker.pk
                for role in ["technical_lead", "content_lead", "operations_lead", "adjudicator"]
            },
            "verifier": reviewer.pk,
        },
    )
    questions = [
        BuzzerQuestion.objects.create(
            round=round,
            stage=stage,
            public_id=f"STAGE-{stage}-Q1",
            version="question-v1",
            source_reference="synthetic-private-pack",
            prepared_by=maker,
            verified_by=reviewer,
            verified_at=timezone.now(),
            private_content={"answer": "SECRET-ANSWER", "presentation_reference": "SECRET-IMAGE"},
        )
        for stage in range(1, 6)
    ]
    return round, questions, teams, maker, reviewer


def ready(fixture):
    round, _, _, maker, reviewer = fixture
    approve_rules(round.pk, reviewer)
    mark_ready(round.pk, maker)
    round.refresh_from_db()
    return round


def test_buzzer_readiness_and_frozen_private_content(buzzer):
    round = ready(buzzer)
    assert len(round.rules_snapshot["buzzer_questions"]) == 5
    question = buzzer[1][0]
    question.private_content = {"answer": "changed", "presentation_reference": "changed"}
    with pytest.raises(ValidationError, match="cannot be edited"):
        question.save()
    overview = participant_overview(buzzer[2][0], round.pk)
    assert overview["eligible"] and overview["capabilities"]["buzzer_supported"]
    assert "SECRET" not in str(overview) and len(overview["buzzer_stages"]) == 5
    assert not participant_overview(buzzer[2][2], round.pk)["eligible"]


def test_buzzer_content_edit_invalidates_verification_and_approval(buzzer):
    round, questions, _, _, reviewer = buzzer
    approve_rules(round.pk, reviewer)
    questions[0].source_reference = "changed reference"
    questions[0].save()
    assert questions[0].verified_by is None
    assert any("independent" in error for error in readiness_errors(round))
    with pytest.raises(ValidationError):
        mark_ready(round.pk, buzzer[3])


def test_buzzer_readiness_rejects_missing_stage_and_client_clock_policy(buzzer):
    round, questions, _, _, _ = buzzer
    questions[0].delete()
    round.rules["buzzer_order_policy"] = "client_click_time"
    assert any("five stages" in error for error in readiness_errors(round))
    assert any("buzzer_order_policy" in error for error in readiness_errors(round))


def action(**data):
    return {"action_id": str(uuid.uuid4()), "reason": "Synthetic buzzer rehearsal", **data}


def start(fixture):
    round = ready(fixture)
    for operation in ["open_lobby", "start"]:
        round.refresh_from_db()
        control_round(
            round.pk, fixture[3], action(action=operation, expected_version=round.control_version)
        )
    round.refresh_from_db()
    return round


def open_window(fixture, question=0):
    round, questions, _, maker, _ = fixture
    round.refresh_from_db()
    current = BuzzerWindow.objects.filter(round=round).order_by("-version").first()
    return control_window(
        round.pk,
        maker,
        action(
            operation="open",
            question_id=questions[question].pk,
            expected_version=round.control_version,
            expected_window_version=current.version if current else 0,
        ),
    )["window"]


def client_for(fixture, index=0):
    client = Client(enforce_csrf_checks=True)
    assert (
        post(
            client,
            "/api/auth/login",
            {"team_code": fixture[2][index].code, "password": "test-only"},
        ).status_code
        == 200
    )
    return client


def post(client, path, data):
    csrf = client.get("/api/auth/csrf").json()["csrf_token"]
    return client.post(path, data, content_type="application/json", HTTP_X_CSRFTOKEN=csrf)


def test_buzzer_retry_duplicates_and_precise_admin_order(buzzer):
    round = start(buzzer)
    window = open_window(buzzer)
    client = client_for(buzzer)
    path = f"/api/rounds/{round.pk}/buzzer/press"
    request = {"action_id": str(uuid.uuid4()), "window_id": window["id"]}
    first = post(client, path, request)
    assert first.status_code == 200
    assert post(client, path, request).json() == first.json()
    assert (
        post(client, path, {"action_id": str(uuid.uuid4()), "window_id": window["id"]}).status_code
        == 200
    )
    desk = staff_desk(round.pk, buzzer[3])
    assert len(desk["entries"]) == 1 and desk["first_team_codes"] == [buzzer[2][0].code]
    assert not desk["order_final"] and BuzzerPress.objects.count() == 2
    assert client.get(f"/api/rounds/{round.pk}/buzzer").json()["own_press"] == first.json()["press"]
    assert not client.get(f"/api/rounds/{round.pk}/buzzer").json()["can_press"]
    request_close = action(
        operation="close", expected_version=round.control_version, expected_window_version=1
    )
    closed = control_window(round.pk, buzzer[3], request_close)
    assert control_window(round.pk, buzzer[3], request_close) == closed
    assert staff_desk(round.pk, buzzer[3])["order_final"]
    assert post(client, path, request).json() == first.json()
    assert (
        post(client, path, {"action_id": str(uuid.uuid4()), "window_id": window["id"]}).status_code
        == 409
    )
    assert (
        client.get(f"/api/rounds/{round.pk}/buzzer/presses/{request['action_id']}").json()
        == first.json()
    )


def test_buzzer_rejects_unqualified_client_time_and_foreign_receipts(buzzer):
    round = start(buzzer)
    window = open_window(buzzer)
    qualified = client_for(buzzer)
    ineligible = client_for(buzzer, 2)
    data = {"action_id": str(uuid.uuid4()), "window_id": window["id"]}
    path = f"/api/rounds/{round.pk}/buzzer/press"
    assert post(ineligible, path, data).status_code == 403
    assert post(qualified, path, {**data, "received_at": "1999-01-01T00:00:00Z"}).status_code == 400
    assert post(qualified, path, data).status_code == 200
    assert (
        ineligible.get(f"/api/rounds/{round.pk}/buzzer/presses/{data['action_id']}").status_code
        == 404
    )
    assert "SECRET" not in str(qualified.get(f"/api/rounds/{round.pk}/buzzer").json())


def test_pause_closes_window_and_resume_needs_new_version(buzzer):
    round = start(buzzer)
    window = open_window(buzzer)
    client = client_for(buzzer)
    path = f"/api/rounds/{round.pk}/buzzer/press"
    for operation in ["freeze", "resume"]:
        round.refresh_from_db()
        control_round(
            round.pk, buzzer[3], action(action=operation, expected_version=round.control_version)
        )
    assert BuzzerClosure.objects.count() == 1
    assert (
        post(client, path, {"action_id": str(uuid.uuid4()), "window_id": window["id"]}).status_code
        == 409
    )
    new_window = open_window(buzzer)
    assert new_window["version"] == 2
    assert (
        post(
            client, path, {"action_id": str(uuid.uuid4()), "window_id": new_window["id"]}
        ).status_code
        == 200
    )


def test_buzzer_guards_qualification_incidents_csrf_and_staff_permissions(buzzer):
    round = start(buzzer)
    window = open_window(buzzer)
    client = client_for(buzzer)
    path = f"/api/rounds/{round.pk}/buzzer/press"
    data = {"action_id": str(uuid.uuid4()), "window_id": window["id"]}
    assert client.post(path, data, content_type="application/json").status_code == 403
    assert client.get(f"/api/staff/rounds/{round.pk}/buzzer").status_code == 403
    assert (
        post(
            client, f"/api/staff/rounds/{round.pk}/buzzer/control", action(operation="close")
        ).status_code
        == 403
    )
    previous = Round.objects.get(number=4)
    Incident.objects.create(
        round=previous,
        category="QUALIFICATION_IMPACT",
        material=True,
        owner=buzzer[3],
        opened_at=timezone.now(),
        affected_scope={"summary": "Synthetic qualification review"},
    )
    assert post(client, path, data).status_code == 403
    assert not BuzzerPress.objects.exists()


def test_equal_server_times_are_not_broken_by_team_code(buzzer):
    from unittest.mock import patch

    round = start(buzzer)
    window = open_window(buzzer)
    first, second = client_for(buzzer), client_for(buzzer, 1)
    timestamp = timezone.now()
    with patch("competition.buzzer.database_now", return_value=timestamp):
        for client in [first, second]:
            assert (
                post(
                    client,
                    f"/api/rounds/{round.pk}/buzzer/press",
                    {"action_id": str(uuid.uuid4()), "window_id": window["id"]},
                ).status_code
                == 200
            )
    desk = staff_desk(round.pk, buzzer[3])
    assert desk["timestamp_tie"] and len(desk["first_team_codes"]) == 2
    assert [entry["position"] for entry in desk["entries"]] == [1, 1]


@pytest.mark.django_db(transaction=True)
def test_close_drains_inflight_earlier_receipt_even_when_later_press_commits_first(buzzer):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event, current_thread
    from unittest.mock import patch

    from django.db import connections
    from django.test import RequestFactory

    from competition.buzzer import admission_fence, lock_press_team, press, queue

    round = start(buzzer)
    window = open_window(buzzer)
    client = client_for(buzzer)
    session = client.session
    earlier_waiting, release_earlier, closing = Event(), Event(), Event()
    earlier_id, later_id = str(uuid.uuid4()), str(uuid.uuid4())

    def delayed_lock(team_id):
        if current_thread().name.startswith("earlier"):
            earlier_waiting.set()
            assert release_earlier.wait(10)
        return lock_press_team(team_id)

    def fenced(round_id, **options):
        if not options.get("shared"):
            closing.set()
        return admission_fence(round_id, **options)

    def submit(identity):
        request = RequestFactory().post("/buzzer")
        request.user, request.session = buzzer[2][0].user, session
        try:
            return press(request, round.pk, {"action_id": identity, "window_id": window["id"]})
        finally:
            connections.close_all()

    def close():
        try:
            return control_window(
                round.pk,
                buzzer[3],
                action(
                    operation="close",
                    expected_version=round.control_version,
                    expected_window_version=1,
                ),
            )
        finally:
            connections.close_all()

    with (
        patch("competition.buzzer.lock_press_team", side_effect=delayed_lock),
        patch("competition.buzzer.admission_fence", side_effect=fenced),
        ThreadPoolExecutor(max_workers=1, thread_name_prefix="earlier") as early_pool,
        ThreadPoolExecutor(max_workers=2) as other_pool,
    ):
        earlier = early_pool.submit(submit, earlier_id)
        try:
            assert earlier_waiting.wait(10)
            later = other_pool.submit(submit, later_id).result(timeout=10)
            assert queue(BuzzerWindow.objects.get(pk=window["id"]))[0][0]["id"] == later_id
            closed = other_pool.submit(close)
            assert closing.wait(10) and not closed.done()
        finally:
            release_earlier.set()
        earlier_result = earlier.result(timeout=10)
        result = closed.result(timeout=10)
    assert result["entries"][0]["id"] == earlier_id
    assert earlier_result["press"]["received_at"] < later["press"]["received_at"]
    assert BuzzerPress.objects.count() == 2 and len(result["entries"]) == 1
    assert BuzzerClosure.objects.get().closed_at >= max(
        BuzzerPress.objects.values_list("admitted_at", flat=True)
    )
