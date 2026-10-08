import uuid
from datetime import timedelta
from unittest.mock import patch

import pytest
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import Client
from django.utils import timezone

from competition.clock import control_round
from competition.demo import demo_rules
from competition.models import (
    CodingRevision,
    CodingSubmission,
    CodingTask,
    ResultSnapshot,
    Round,
    Team,
    TeamSession,
)
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


def post(client, path, data):
    csrf = client.get("/api/auth/csrf").json()["csrf_token"]
    return client.post(path, data, content_type="application/json", HTTP_X_CSRFTOKEN=csrf)


def logical(response):
    return {key: value for key, value in response.json().items() if key != "request_id"}


def start(fixture):
    round, _, _, maker, _ = fixture
    ready(fixture)
    for action in ["open_lobby", "start"]:
        round.refresh_from_db()
        control_round(
            round.pk,
            maker,
            {
                "action": action,
                "action_id": str(uuid.uuid4()),
                "reason": "Synthetic coding rehearsal",
                "expected_version": round.control_version,
            },
        )
    round.refresh_from_db()
    return round


def assigned_client(fixture, index=0):
    round, _, teams, maker, _ = fixture
    client = Client(enforce_csrf_checks=True)
    assert (
        post(
            client, "/api/auth/login", {"team_code": teams[index].code, "password": "test-only"}
        ).status_code
        == 200
    )
    session = TeamSession.objects.get(session_key=client.session.session_key)
    from competition.coding import assign_workstation

    assign_workstation(
        round.pk,
        maker,
        {
            "action_id": str(uuid.uuid4()),
            "reason": "Verified lab workstation",
            "session_id": session.pk,
            "label": f"DESK-{index}",
            "expected_version": 0,
            "evidence_refs": ["station-sheet"],
        },
    )
    return client


def save(fixture, client, task=0, revision=0, **extra):
    round, tasks, _, _, _ = fixture
    data = {
        "action_id": str(uuid.uuid4()),
        "body": "synthetic source",
        "language": tasks[task].languages[0],
        "expected_revision": revision,
        **extra,
    }
    path = f"/api/rounds/{round.pk}/coding/tasks/{tasks[task].pk}/response"
    return post(client, path, data), data, path


def test_saves_are_revisioned_replayable_and_never_expose_private_tests(coding):
    round = start(coding)
    client = assigned_client(coding)
    view = client.get(f"/api/rounds/{round.pk}/coding/submission")
    assert view.status_code == 200 and "private correct answer" not in view.content.decode()
    saved, data, path = save(coding, client)
    assert saved.status_code == 200 and saved.json()["revision"] == 1
    assert logical(post(client, path, data)) == logical(saved)
    assert save(coding, client)[0].status_code == 409
    assert post(client, path, {**data, "body": "changed payload"}).status_code == 409
    assert CodingRevision.objects.count() == 1


def test_final_locks_exact_saved_versions_and_replays_after_end(coding):
    round, tasks, _, maker, _ = coding
    start(coding)
    client = assigned_client(coding)
    assert save(coding, client)[0].status_code == 200
    final_data = {
        "action_id": str(uuid.uuid4()),
        "expected_revisions": {
            str(task.pk): 1 if index == 0 else 0 for index, task in enumerate(tasks)
        },
    }
    path = f"/api/rounds/{round.pk}/coding/finalize"
    response = post(client, path, final_data)
    assert response.status_code == 200
    assert save(coding, client, revision=1)[0].status_code == 409
    round.refresh_from_db()
    control_round(
        round.pk,
        maker,
        {
            "action": "end",
            "action_id": str(uuid.uuid4()),
            "reason": "End coding test",
            "expected_version": round.control_version,
        },
    )
    assert logical(post(client, path, final_data)) == logical(response)
    assert CodingSubmission.objects.count() == 2


def test_cutoff_freezes_last_saved_work_and_preserves_no_submission_outcome(coding):
    round, _, teams, maker, _ = coding
    start(coding)
    client = assigned_client(coding)
    assert save(coding, client)[0].status_code == 200
    when = round.deadline_at + timedelta(seconds=5)
    with patch("competition.coding.database_now", return_value=when):
        assert save(coding, client, revision=1)[0].status_code == 409
    with patch("competition.clock.database_now", return_value=when):
        control_round(
            round.pk,
            maker,
            {
                "action": "end",
                "action_id": str(uuid.uuid4()),
                "reason": "Persist expired coding",
                "expected_version": round.control_version,
            },
        )
    final = CodingSubmission.objects.get(team=teams[0])
    assert final.kind == "CUTOFF" and final.submitted_at == round.deadline_at
    assert len(final.manifest) == 1
    assert CodingSubmission.objects.get(team=teams[1]).kind == "NO_SUBMISSION"


def test_a_second_browser_cannot_read_or_save_assigned_work(coding):
    round = start(coding)
    assigned_client(coding)
    second = Client(enforce_csrf_checks=True)
    assert (
        post(
            second, "/api/auth/login", {"team_code": coding[2][0].code, "password": "test-only"}
        ).status_code
        == 200
    )
    view = second.get(f"/api/rounds/{round.pk}/coding/submission").json()
    assert view["tasks"] == [] and not view["assigned"]
    assert save(coding, second)[0].status_code == 403
