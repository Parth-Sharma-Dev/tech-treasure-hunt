import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from threading import Barrier

import pytest
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.db import connections
from django.test import Client, override_settings
from django.utils import timezone

from competition.answers import answer_digest
from competition.models import (
    AuditEvent,
    Completion,
    Mission,
    Round,
    SubmissionDecision,
    Team,
    TeamLoginWindow,
    TeamSession,
    Visit,
)
from competition.sessions import safe_return_path

pytestmark = pytest.mark.django_db
TEST_PASSWORD = "synthetic-test-only-password"


@pytest.fixture(autouse=True)
def fast_test_passwords(settings):
    settings.PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]


@pytest.fixture
def team():
    user = get_user_model().objects.create_user(
        username="internal-username", password=TEST_PASSWORD
    )
    return Team.objects.create(code="TEST-01", name="Test team", member_count=3, user=user)


def csrf_post(client, path, data):
    token = client.get("/api/auth/csrf").json()["csrf_token"]
    return client.post(path, data, content_type="application/json", HTTP_X_CSRFTOKEN=token)


def sign_in(client, **extra):
    return csrf_post(
        client, "/api/auth/login", {"team_code": "TEST-01", "password": TEST_PASSWORD, **extra}
    )


def test_login_logout_and_own_team_identity(team):
    client = Client(enforce_csrf_checks=True)
    assert client.get("/api/me").status_code == 401
    response = sign_in(client, team_id=999)
    assert response.status_code == 200
    assert response.json()["team"]["code"] == team.code
    assert response.json()["session"]["active_count"] == 1
    assert client.get("/api/me?team_id=999").json()["team"]["code"] == team.code
    assert csrf_post(client, "/api/auth/logout", {}).status_code == 200
    assert client.get("/api/me").status_code == 401
    assert TeamSession.objects.get(team=team).revoked_at is not None


def test_login_and_logout_require_csrf(team):
    client = Client(enforce_csrf_checks=True)
    response = client.post(
        "/api/auth/login",
        {"team_code": team.code, "password": TEST_PASSWORD},
        content_type="application/json",
    )
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "csrf_failed"
    sign_in(client)
    assert client.post("/api/auth/logout").status_code == 403
    assert client.get("/api/me").status_code == 200


def test_repeated_login_same_browser_does_not_allocate_extra_sessions(team):
    client = Client(enforce_csrf_checks=True)
    assert sign_in(client).status_code == 200
    key = client.cookies["sessionid"].value
    assert sign_in(client).status_code == 200
    assert client.cookies["sessionid"].value == key
    assert TeamSession.objects.filter(team=team).count() == 1


def test_results_return_destination_is_local_and_retained():
    assert safe_return_path("/rounds/12/results") == "/rounds/12/results"
    assert safe_return_path("https://example.com/rounds/12/results") == "/lobby"
    assert safe_return_path("/rounds/12/results?next=https://example.com") == "/lobby"


@pytest.mark.django_db(transaction=True)
def test_concurrent_logins_allocate_at_most_four_sessions(team):
    barrier = Barrier(6)

    def attempt():
        try:
            client = Client(enforce_csrf_checks=True)
            barrier.wait(timeout=10)
            return sign_in(client).status_code
        finally:
            connections.close_all()

    with ThreadPoolExecutor(max_workers=6) as pool:
        outcomes = list(pool.map(lambda _: attempt(), range(6)))
    assert outcomes.count(200) == 4
    assert outcomes.count(409) == 2
    assert TeamSession.objects.filter(team=team, revoked_at=None).count() == 4


def test_expired_sessions_do_not_reserve_slots(team):
    for _ in range(4):
        assert sign_in(Client(enforce_csrf_checks=True)).status_code == 200
    TeamSession.objects.filter(team=team).update(expires_at=timezone.now() - timedelta(seconds=1))
    client = Client(enforce_csrf_checks=True)
    assert sign_in(client).status_code == 200
    assert client.get("/api/me").json()["session"]["active_count"] == 1


def test_session_version_and_team_status_are_checked_on_every_request(team):
    client = Client(enforce_csrf_checks=True)
    sign_in(client)
    team.session_version += 1
    team.save()
    assert client.get("/api/me").status_code == 401
    assert sign_in(client).status_code == 200
    team.status = Team.Status.DISQUALIFIED
    team.save()
    assert client.get("/api/me").json()["team"]["status"] == "DISQUALIFIED"
    assert client.get("/api/practice").status_code == 403


def test_staff_revocation_is_audited_idempotent_and_does_not_revoke_teammates(team):
    clients = [Client(enforce_csrf_checks=True), Client(enforce_csrf_checks=True)]
    for client in clients:
        sign_in(client)
    target = TeamSession.objects.get(session_key=clients[0].cookies["sessionid"].value)
    staff = get_user_model().objects.create_user(username="support", is_staff=True)
    staff.user_permissions.add(
        Permission.objects.get(content_type__app_label="competition", codename="control_round")
    )
    operator = Client(enforce_csrf_checks=True)
    operator.force_login(staff)
    path = f"/api/staff/teams/{team.pk}/sessions/{target.pk}/revoke"
    data = {"action_id": str(uuid.uuid4()), "reason": "Lost camera-browser session"}
    response = csrf_post(operator, path, data)
    assert response.status_code == 200
    assert csrf_post(operator, path, data).json()["revoked_at"] == response.json()["revoked_at"]
    assert AuditEvent.objects.filter(action="revoke_team_session").count() == 1
    assert clients[0].get("/api/me").status_code == 401
    assert clients[1].get("/api/me").status_code == 200
    assert csrf_post(operator, path, {**data, "reason": "Changed payload"}).status_code == 409
    assert sign_in(clients[0]).status_code == 200
    assert clients[0].cookies["sessionid"].value != target.session_key


def test_participant_cannot_revoke_any_session_or_enter_admin(team):
    client = Client(enforce_csrf_checks=True)
    sign_in(client)
    target = TeamSession.objects.get(team=team)
    response = csrf_post(
        client,
        f"/api/staff/teams/{team.pk}/sessions/{target.pk}/revoke",
        {"action_id": str(uuid.uuid4()), "reason": "Unauthorized"},
    )
    assert response.status_code == 403
    target.refresh_from_db()
    assert target.revoked_at is None
    assert client.get("/admin/").status_code == 302


def test_staff_accounts_cannot_use_team_login_or_team_read_endpoints(team):
    team.user.is_staff = True
    team.user.save()
    client = Client(enforce_csrf_checks=True)
    assert sign_in(client).status_code == 401
    client.force_login(team.user)
    assert client.get("/api/me").status_code == 401


def test_wrong_password_rate_limit_persists_and_expires(team):
    client = Client(enforce_csrf_checks=True)
    for _ in range(5):
        assert sign_in(client, password="wrong").status_code == 401
    response = sign_in(client)
    assert response.status_code == 429
    assert int(response["Retry-After"]) > 0
    TeamLoginWindow.objects.filter(team=team).update(
        started_at=timezone.now() - timedelta(seconds=61)
    )
    assert sign_in(client).status_code == 200
    assert TeamLoginWindow.objects.get(team=team).failed_attempts == 0


@pytest.mark.parametrize(
    "destination",
    [
        "https://evil.example",
        "//evil.example",
        "/\\evil.example",
        "/%2F%2Fevil.example",
        "javascript:alert(1)",
        "/admin/",
    ],
)
def test_unsafe_return_destinations_are_replaced_with_lobby(destination):
    assert safe_return_path(destination) == "/lobby"


def test_mission_return_link_survives_login(team):
    path = "/missions/" + "a" * 43
    response = sign_in(Client(enforce_csrf_checks=True), return_to=path)
    assert response.json()["return_to"] == path


@override_settings(ANSWER_HMAC_KEY="test-only-answer-key")
def test_practice_acceptance_never_writes_competitive_evidence(team):
    round = Round.objects.create(number=1, title="Test hunt")
    mission = Mission.objects.create(
        round=round,
        public_id="PRACTICE",
        is_practice=True,
        hint="Try 0427.",
        keyword="PRACTICE",
        qr_location="Test",
        clue_location="Test",
        answer_verifiers=[],
    )
    mission.answer_verifiers = [
        {"version": "test-v1", "digest": answer_digest(mission.pk, "test-v1", "0427")}
    ]
    mission.save()
    client = Client(enforce_csrf_checks=True)
    sign_in(client)
    assert client.get("/api/practice").json()["hint"] == "Try 0427."
    assert csrf_post(client, "/api/practice/submit", {"answer": "427"}).status_code == 400
    assert (
        csrf_post(client, "/api/practice/submit", {"answer": "0000"}).json()["outcome"]
        == "incorrect"
    )
    response = csrf_post(client, "/api/practice/submit", {"answer": "0427"})
    assert response.json()["outcome"] == "accepted"
    assert response.json()["points_awarded"] == 0
    assert (
        Completion.objects.count()
        == SubmissionDecision.objects.count()
        == Visit.objects.count()
        == 0
    )
    assert not any(
        key in client.get("/api/practice").json() for key in ("answer", "answer_verifiers", "token")
    )
