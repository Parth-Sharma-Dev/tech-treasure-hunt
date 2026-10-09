
import pytest
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.utils import timezone

from competition.demo import demo_rules
from competition.models import BuzzerQuestion, ResultSnapshot, Round, Team
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
