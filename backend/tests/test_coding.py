
import pytest
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.utils import timezone

from competition.demo import demo_rules
from competition.models import CodingTask, ResultSnapshot, Round, Team
from competition.rules import approve_rules, mark_ready, readiness_errors

pytestmark = pytest.mark.django_db


@pytest.fixture
def coding(settings):
    settings.PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]
    users = get_user_model()
    maker = users.objects.create_superuser(username="coding-maker", password="test-only")
    reviewer = users.objects.create_superuser(username="coding-reviewer", password="test-only")
    teams = [
        Team.objects.create(
            code=f"CODE-{i}",
            name=f"Synthetic coding {i}",
            is_demo=True,
            member_count=3,
            user=users.objects.create_user(username=f"code-user-{i}", password="test-only"),
        )
        for i in range(2)
    ]
    previous = Round.objects.create(
        number=2, title="Synthetic qualifying fixture", state="FINALIZED", is_demo=True
    )
    ResultSnapshot.objects.create(
        round=previous,
        revision=1,
        status="FINAL",
        qualifier_codes=[team.code for team in teams],
        published_at=timezone.now(),
        maker=maker,
        approver=reviewer,
    )
    rules = {
        **demo_rules(3),
        "submission_policy": "locked_final_with_cutoff_autofinalize",
        "ranking_policy": "score_correct_tasks_final_time",
        "qualification_tie_policy": "supervised_reserve_task",
        "one_workstation_per_team": True,
        "score_precision": 3,
        "language_versions": {"PYTHON": "synthetic lab version", "C": "synthetic lab version"},
    }
    round = Round.objects.create(
        number=3,
        title="Synthetic coding",
        is_demo=True,
        delivery_mode="CODING",
        active_budget_ms=60000,
        advancement_count=1,
        rules_version="coding-v1",
        rules=rules,
        owners={
            **{
                key: maker.pk
                for key in ["technical_lead", "content_lead", "operations_lead", "adjudicator"]
            },
            "verifier": reviewer.pk,
        },
    )
    tasks = []
    for category, points in [
        ("OUTPUT", 15),
        ("DEBUG", 25),
        ("FILL", 20),
        ("SHORT", 30),
        ("LOGIC", 10),
    ]:
        tasks.append(
            CodingTask.objects.create(
                round=round,
                public_id=category,
                category=category,
                prompt=f"Synthetic {category}",
                languages=["PYTHON", "C"] if category in ["DEBUG", "FILL", "SHORT"] else ["TEXT"],
                points=points,
                version="task-v1",
                private_rubric={
                    "test_cases": [
                        {"id": "a", "input": "private input", "expected": "private output"},
                        {"id": "b", "input": "hidden", "expected": "hidden"},
                    ]
                }
                if category == "SHORT"
                else {"expected": "private correct answer"},
                prepared_by=maker,
                verified_by=reviewer,
                verified_at=timezone.now(),
            )
        )
    return round, tasks, teams, maker, reviewer


def ready(fixture):
    round, _, _, maker, reviewer = fixture
    approve_rules(round.pk, reviewer)
    mark_ready(round.pk, maker)
    round.refresh_from_db()
    return round


def test_native_coding_readiness_freezes_the_verified_task_set(coding):
    round = ready(coding)
    assert len(round.rules_snapshot["coding_tasks"]) == 5
    task = coding[1][0]
    task.prompt = "Unapproved edit"
    with pytest.raises(ValidationError, match="frozen"):
        task.save()


def test_coding_rejects_wrong_totals_and_unverified_content(coding):
    round, tasks, _, _, _ = coding
    tasks[0].points = 14
    tasks[0].save()
    errors = readiness_errors(round)
    assert any("Category totals" in error for error in errors)
    assert any("independent content" in error for error in errors)
