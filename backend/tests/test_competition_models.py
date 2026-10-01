import uuid

import pytest
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.utils import timezone

from competition.models import (
    AttemptState,
    AuditEvent,
    Completion,
    Mission,
    Round,
    SubmissionDecision,
    Team,
    Visit,
)

pytestmark = pytest.mark.django_db


@pytest.fixture
def records():
    user = get_user_model().objects.create_user(username="TEST-01")
    team = Team.objects.create(code="TEST-01", name="Test team", user=user, member_count=3)
    round = Round.objects.create(number=1, title="Test hunt")
    mission = Mission.objects.create(
        round=round,
        public_id="M01",
        hint="Test clue",
        keyword="LOOP",
        qr_location="Demo start",
        clue_location="Demo finish",
        answer_verifiers=[],
    )
    return team, round, mission


def make_decision(team, round, mission, **overrides):
    values = {
        "team": team,
        "round": round,
        "mission": mission,
        "idempotency_key": uuid.uuid4(),
        "request_fingerprint": "a" * 64,
        "ingress_at": timezone.now(),
        "admitted_at": timezone.now(),
        "active_elapsed_ms": 123,
        "rules_version": "test-v1",
        "outcome": "accepted",
        "response_snapshot": {"outcome": "accepted"},
    }
    values.update(overrides)
    return SubmissionDecision.objects.create(**values)


@pytest.mark.parametrize("kind", ["visit", "attempt", "completion"])
def test_one_record_per_team_mission(records, kind):
    team, round, mission = records
    now = timezone.now()
    if kind == "visit":
        model, fields = (
            Visit,
            {"first_opened_at": now, "last_opened_at": now, "access_method": "QR"},
        )
    elif kind == "attempt":
        model, fields = AttemptState, {}
    else:
        model, fields = (
            Completion,
            {
                "source_decision": make_decision(team, round, mission),
                "effective_at": now,
                "effective_active_ms": 123,
            },
        )
    model.objects.create(team=team, mission=mission, **fields)
    with pytest.raises(IntegrityError), transaction.atomic():
        model.objects.create(team=team, mission=mission, **fields)


def test_decision_key_is_unique_per_team_round(records):
    team, round, mission = records
    key = uuid.uuid4()
    make_decision(team, round, mission, idempotency_key=key)
    with pytest.raises(IntegrityError), transaction.atomic():
        make_decision(team, round, mission, idempotency_key=key)


def test_completion_requires_one_source(records):
    team, _, mission = records
    with pytest.raises(IntegrityError), transaction.atomic():
        Completion.objects.create(
            team=team,
            mission=mission,
            effective_at=timezone.now(),
            effective_active_ms=1,
        )


def test_source_team_and_round_are_validated(records):
    team, round, mission = records
    decision = make_decision(team, round, mission)
    other_user = get_user_model().objects.create_user(username="TEST-02")
    other_team = Team.objects.create(code="TEST-02", name="Other", user=other_user, member_count=4)
    completion = Completion(
        team=other_team,
        mission=mission,
        source_decision=decision,
        effective_at=timezone.now(),
        effective_active_ms=1,
    )
    with pytest.raises(ValidationError, match="different team"):
        completion.clean()
    decision.round = Round.objects.create(number=2, title="Quiz")
    with pytest.raises(ValidationError, match="does not belong"):
        decision.clean()


def test_practice_cannot_create_competitive_completion(records):
    team, round, mission = records
    mission.is_practice = True
    mission.save()
    completion = Completion(
        team=team,
        mission=mission,
        source_decision=make_decision(team, round, mission),
        effective_at=timezone.now(),
        effective_active_ms=1,
    )
    with pytest.raises(ValidationError, match="Practice"):
        completion.clean()


def test_evidence_cannot_be_edited_or_deleted(records):
    team, round, mission = records
    decision = make_decision(team, round, mission)
    decision.outcome = "incorrect"
    with pytest.raises(ValidationError, match="immutable"):
        decision.save()
    with pytest.raises(ValidationError, match="cannot be deleted"):
        decision.delete()
    decision.refresh_from_db()
    assert decision.outcome == "accepted"


def test_audit_action_identity_is_unique(records):
    team, _, _ = records
    action_id = uuid.uuid4()
    AuditEvent.objects.create(action_id=action_id, actor=team.user, action="test", reason="Test")
    with pytest.raises(IntegrityError), transaction.atomic():
        AuditEvent.objects.create(
            action_id=action_id, actor=team.user, action="test", reason="Test"
        )


@pytest.mark.parametrize(
    "field,value", [("number", 6), ("active_budget_ms", 0), ("advancement_count", 0)]
)
def test_round_configuration_constraints(field, value):
    values = {"number": 1, "title": "Invalid", field: value}
    with pytest.raises(IntegrityError), transaction.atomic():
        Round.objects.create(**values)
