import uuid
from datetime import timedelta

import pytest
from django.contrib.auth import get_user_model
from django.test import Client
from django.utils import timezone

from competition.api import ApiProblem
from competition.models import AuditEvent, Incident, Round, Team, TeamSession
from competition.roster import credentials, propose_roster, review_roster

pytestmark = pytest.mark.django_db


@pytest.fixture
def staff():
    users = get_user_model()
    return (
        users.objects.create_superuser(username="roster-maker", password=None),
        users.objects.create_superuser(username="roster-verifier", password=None),
    )


def action(**data):
    return {
        "action_id": str(uuid.uuid4()),
        "reason": "Synthetic roster source verification",
        **data,
    }


def row(code="ROSTER-1"):
    return {
        "code": code,
        "name": "Synthetic roster team",
        "leader_name": "Synthetic leader",
        "member_count": 3,
        "roster_reference": "Synthetic application",
        "status": "ACTIVE",
    }


def create(staff):
    maker, verifier = staff
    proposal = propose_roster(maker, action(is_demo=True, rows=[row()]))
    review_roster(verifier, action(proposal_id=proposal["proposal_id"], evidence_confirmed=True))
    return Team.objects.get(code="ROSTER-1")


def test_roster_creation_requires_review_and_replays_atomically(staff):
    maker, verifier = staff
    request = action(is_demo=False, rows=[row()])
    proposal = propose_roster(maker, request)
    assert not Team.objects.exists()
    assert propose_roster(maker, request) == proposal
    review = action(proposal_id=proposal["proposal_id"], evidence_confirmed=True)
    with pytest.raises(ApiProblem, match="different verifier"):
        review_roster(maker, review)
    response = review_roster(verifier, review)
    assert review_roster(verifier, review) == response
    assert Team.objects.count() == 1
    assert not Team.objects.get().user.has_usable_password()


def test_roster_csv_validates_duplicates_and_credentials_conflicts(staff):
    maker, _ = staff
    with pytest.raises(ApiProblem, match="duplicate"):
        propose_roster(maker, action(is_demo=True, rows=[row(), row()]))
    get_user_model().objects.create_user(username="ROSTER-MAKER")
    with pytest.raises(ApiProblem, match="unused account"):
        propose_roster(maker, action(is_demo=True, rows=[row("ROSTER-MAKER")]))
    proposal = propose_roster(
        maker,
        action(
            is_demo=True,
            csv="code,name,leader_name,member_count,roster_reference,status\nROSTER-2,Synthetic,Leader,4,Ref,ACTIVE\n",
        ),
    )
    assert proposal["rows"][0]["member_count"] == 4


def test_roster_release_blocks_creation_and_identity_changes(staff):
    team = create(staff)
    maker, _ = staff
    Round.objects.create(number=1, title="Released", is_demo=True, state="READY")
    with pytest.raises(ApiProblem, match="before any"):
        propose_roster(maker, action(is_demo=True, rows=[row("ROSTER-2")]))
    changed = {**row(), "name": "Changed after release"}
    with pytest.raises(ApiProblem, match="identity is locked"):
        propose_roster(maker, action(is_demo=True, rows=[changed]))
    assert Team.objects.get(pk=team.pk).name == row()["name"]


def test_withdrawal_revokes_sessions_and_blocks_postfinal_progression(staff):
    team = create(staff)
    maker, verifier = staff
    round = Round.objects.create(number=1, title="Finalized", is_demo=True, state="FINALIZED")
    session = TeamSession.objects.create(
        team=team,
        session_key="test-session",
        session_version=1,
        last_seen_at=timezone.now(),
        expires_at=timezone.now() + timedelta(hours=1),
    )
    proposal = propose_roster(maker, action(is_demo=True, rows=[{**row(), "status": "WITHDRAWN"}]))
    review_roster(verifier, action(proposal_id=proposal["proposal_id"], evidence_confirmed=True))
    team.refresh_from_db()
    session.refresh_from_db()
    assert team.status == "WITHDRAWN" and team.session_version == 2
    assert session.revoked_at
    assert Incident.objects.filter(
        round=round, category="QUALIFICATION_IMPACT", material=True, closed_at__isnull=True
    ).exists()
    with pytest.raises(ApiProblem, match="Reactivation"):
        propose_roster(maker, action(is_demo=True, rows=[row()]))


def test_stale_roster_review_cannot_cross_release(staff):
    maker, verifier = staff
    proposal = propose_roster(maker, action(is_demo=True, rows=[row()]))
    Round.objects.create(number=1, title="Released while reviewing", is_demo=True, state="READY")
    with pytest.raises(ApiProblem, match="changed"):
        review_roster(
            verifier, action(proposal_id=proposal["proposal_id"], evidence_confirmed=True)
        )
    assert not Team.objects.exists()
    review_roster(verifier, action(proposal_id=proposal["proposal_id"], reject=True))


def test_credential_issue_does_not_record_plaintext_and_revokes_old_access(staff):
    team = create(staff)
    maker, _ = staff
    request = action(password="Synthetic-Team-Secret-913", expected_version=team.session_version)
    response = credentials(maker, team.pk, request)
    assert credentials(maker, team.pk, request) == response
    team.refresh_from_db()
    team.user.refresh_from_db()
    assert team.user.check_password(request["password"])
    assert request["password"] not in str(list(AuditEvent.objects.values()))
    with pytest.raises(ApiProblem, match="refresh"):
        credentials(maker, team.pk, action(password="New-Synthetic-Secret-234", expected_version=1))


def test_roster_endpoints_reject_participants(staff):
    team = create(staff)
    client = Client()
    client.force_login(team.user)
    assert client.get("/api/staff/roster").status_code == 403
    assert (
        client.post(
            "/api/staff/roster/change",
            action(operation="propose", is_demo=True, rows=[row()]),
            content_type="application/json",
        ).status_code
        == 403
    )
