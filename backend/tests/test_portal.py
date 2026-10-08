from datetime import timedelta

import pytest
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import Client
from django.utils import timezone

from competition.api import ApiProblem
from competition.models import EventAnnouncement, Round, RoundInformation, Team
from competition.portal import dashboard, participant_overview, publish_information

pytestmark = pytest.mark.django_db


@pytest.fixture
def portal(settings):
    settings.PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]
    users = get_user_model()
    maker = users.objects.create_superuser(username="portal-maker", password=None)
    reviewer = users.objects.create_superuser(username="portal-reviewer", password=None)
    team = Team.objects.create(
        code="PORTAL-1",
        name="Synthetic portal team",
        member_count=3,
        is_demo=True,
        user=users.objects.create_user(username="portal-team", password="synthetic-test-only"),
    )
    rounds = [
        Round.objects.create(number=number, title=f"Round {number}", is_demo=True)
        for number in range(1, 6)
    ]
    return team, rounds, maker, reviewer


def test_information_requires_independent_review_and_preserves_last_publication(portal):
    team, rounds, maker, reviewer = portal
    info = RoundInformation.objects.create(
        round=rounds[0],
        summary="Released overview",
        venue="Synthetic lab",
        instructions="Released instructions",
        prepared_by=maker,
        contacts=[{"name": "Synthetic organizer", "role": "Help desk", "channel": "Desk A"}],
    )
    assert participant_overview(team, rounds[0].pk)["information"].get("summary") is None
    with pytest.raises(ValidationError, match="different verifier"):
        publish_information(RoundInformation, info.pk, maker)
    publish_information(RoundInformation, info.pk, reviewer)
    info.refresh_from_db()
    info.summary = "Private draft revision"
    info.save(update_fields=["summary"])
    result = participant_overview(team, rounds[0].pk)
    assert result["information"]["summary"] == "Released overview"
    assert result["information"]["instructions"] == ""
    rounds[0].state = "READY"
    rounds[0].save()
    assert (
        participant_overview(team, rounds[0].pk)["information"]["instructions"]
        == "Released instructions"
    )


def test_ineligible_teams_see_public_overview_but_no_restricted_instructions(portal):
    team, rounds, maker, reviewer = portal
    rounds[2].state = "LIVE"
    rounds[2].save()
    info = RoundInformation.objects.create(
        round=rounds[2],
        summary="Coding overview",
        instructions="Private activity instructions",
        prepared_by=maker,
    )
    publish_information(RoundInformation, info.pk, reviewer)
    result = participant_overview(team, rounds[2].pk)
    assert result["information"]["summary"] == "Coding overview"
    assert (
        not result["capabilities"]["enter_activity"] and not result["capabilities"]["submit_code"]
    )
    assert result["information"]["instructions"] == "" and result["rules"] is None
    assert result["eligibility_reason"] == "Eligibility awaits final Round 2 results."


def test_dashboard_latest_attempt_cohort_and_round5_release_guard(portal):
    team, rounds, _, _ = portal
    newer = Round.objects.create(number=1, attempt_no=2, title="New attempt", is_demo=True)
    foreign = Round.objects.create(number=1, attempt_no=3, title="Other cohort")
    assert dashboard(team)["rounds"][0]["id"] == newer.pk
    with pytest.raises(ApiProblem, match="latest attempt"):
        participant_overview(team, rounds[0].pk)
    for identifier in [foreign.pk, rounds[4].pk]:
        with pytest.raises(ApiProblem, match="not available"):
            participant_overview(team, identifier)


def test_only_published_announcements_are_visible_and_can_be_withdrawn(portal):
    team, rounds, maker, reviewer = portal
    notice = EventAnnouncement.objects.create(
        title="Synthetic notice", body="Go to the desk", is_demo=True, prepared_by=maker
    )
    EventAnnouncement.objects.create(
        title="Private draft", body="Not released", is_demo=True, prepared_by=maker
    )
    assert dashboard(team)["announcements"] == []
    publish_information(EventAnnouncement, notice.pk, reviewer)
    assert dashboard(team)["announcements"][0]["body"] == "Go to the desk"
    notice.refresh_from_db()
    notice.visible = False
    notice.save()
    assert len(dashboard(team)["announcements"]) == 1
    publish_information(EventAnnouncement, notice.pk, reviewer)
    assert dashboard(team)["announcements"] == []


def test_invalid_schedule_and_contact_schema_cannot_be_published(portal):
    _, rounds, maker, reviewer = portal
    now = timezone.now()
    info = RoundInformation.objects.create(
        round=rounds[0],
        prepared_by=maker,
        scheduled_start=now,
        scheduled_end=now - timedelta(minutes=1),
    )
    with pytest.raises(ValidationError, match="end must follow"):
        publish_information(RoundInformation, info.pk, reviewer)
    info.scheduled_end = now + timedelta(minutes=1)
    info.contacts = [{"name": "Name", "role": "Role", "secret": "Unapproved field"}]
    info.save()
    with pytest.raises(ValidationError, match="support name"):
        publish_information(RoundInformation, info.pk, reviewer)


def test_portal_endpoints_require_team_session_and_redact_draft_instructions(portal):
    team, rounds, maker, reviewer = portal
    client = Client(enforce_csrf_checks=True)
    assert client.get("/api/rounds").status_code == 401
    token = client.get("/api/auth/csrf").json()["csrf_token"]
    assert (
        client.post(
            "/api/auth/login",
            {"team_code": team.code, "password": "synthetic-test-only"},
            content_type="application/json",
            HTTP_X_CSRFTOKEN=token,
        ).status_code
        == 200
    )
    info = RoundInformation.objects.create(
        round=rounds[2], prepared_by=maker, instructions="Restricted instructions"
    )
    publish_information(RoundInformation, info.pk, reviewer)
    assert (
        client.get(f"/api/rounds/{rounds[2].pk}/overview").json()["information"]["instructions"]
        == ""
    )
    assert client.get(f"/api/rounds/{rounds[4].pk}/overview").status_code == 404
    assert len(client.get("/api/rounds").json()["rounds"]) == 5
