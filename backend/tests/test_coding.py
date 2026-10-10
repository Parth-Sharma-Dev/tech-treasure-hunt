import os
import shutil
import subprocess
import uuid
from datetime import timedelta
from pathlib import Path
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
    original = assigned_client(coding)
    second = Client(enforce_csrf_checks=True)
    assert (
        post(
            second, "/api/auth/login", {"team_code": coding[2][0].code, "password": "test-only"}
        ).status_code
        == 409
    )
    assert second.get(f"/api/rounds/{round.pk}/coding/submission").status_code == 401
    assert post(original, "/api/auth/logout", {}).status_code == 200
    assert (
        post(
            second, "/api/auth/login", {"team_code": coding[2][0].code, "password": "test-only"}
        ).status_code
        == 200
    )
    view = second.get(f"/api/rounds/{round.pk}/coding/submission").json()
    assert view["tasks"] == [] and not view["assigned"]
    assert save(coding, second)[0].status_code == 403


def ended_bundle(fixture):
    round, tasks, teams, maker, _ = fixture
    start(fixture)
    client = assigned_client(fixture)
    for index in range(len(tasks)):
        assert save(fixture, client, task=index)[0].status_code == 200
    assert (
        post(
            client,
            f"/api/rounds/{round.pk}/coding/finalize",
            {
                "action_id": str(uuid.uuid4()),
                "expected_revisions": {str(task.pk): 1 for task in tasks},
            },
        ).status_code
        == 200
    )
    round.refresh_from_db()
    control_round(
        round.pk,
        maker,
        {
            "action": "end",
            "action_id": str(uuid.uuid4()),
            "reason": "Review coding results",
            "expected_version": round.control_version,
        },
    )
    round.refresh_from_db()
    return CodingSubmission.objects.get(team=teams[0])


def grade_data(fixture, submission, passed=None):
    hashes = {item["task_id"]: item["source_hash"] for item in submission.manifest}
    return {
        "action_id": str(uuid.uuid4()),
        "submission_id": submission.pk,
        "reason": "Lab evidence checked",
        "evidence_refs": ["lab-output-sheet"],
        "time_evidence": ["supervisor-clock-sheet"],
        "supervisor_time": submission.submitted_at.isoformat(),
        "supervisor_id": fixture[3].pk,
        "grades": [
            {
                "task_id": task.pk,
                "task_version": task.version,
                "source_hash": hashes.get(task.pk, ""),
                **(
                    {"passed_tests": passed if passed is not None else ["a"]}
                    if task.category == "SHORT"
                    else {"correct": True}
                ),
            }
            for task in fixture[1]
        ],
    }


def test_reviewed_lab_partial_marks_ranking_and_final_qualification(coding):
    from competition.api import ApiProblem
    from competition.coding_results import approve_judgment, propose_judgment
    from competition.results import approve_result, build_preview, propose_result

    round, _, teams, maker, reviewer = coding
    submission = ended_bundle(coding)
    proposed = propose_judgment(round.pk, maker, grade_data(coding, submission))
    assert proposed["score"] == "85.000" and proposed["fully_correct_tasks"] == 4
    with pytest.raises(ApiProblem, match="different verifier"):
        approve_judgment(
            round.pk,
            maker,
            {
                "action_id": str(uuid.uuid4()),
                "proposal_id": proposed["judgment_proposal_id"],
                "reason": "Attempt self-review",
                "evidence_confirmed": True,
            },
        )
    review = {
        "action_id": str(uuid.uuid4()),
        "proposal_id": proposed["judgment_proposal_id"],
        "reason": "Independent lab review",
        "evidence_confirmed": True,
    }
    accepted = approve_judgment(round.pk, reviewer, review)
    assert approve_judgment(round.pk, reviewer, review) == accepted
    round.refresh_from_db()
    preview = build_preview(round, timezone.now())
    assert preview["evidence_gaps"] == [] and preview["entries"][0]["score"] == 85
    assert preview["entries"][0]["fully_correct_tasks"] == 4
    provisional = propose_result(
        round.pk,
        maker,
        {
            "action_id": str(uuid.uuid4()),
            "reason": "Provisional coding results",
            "status": "PROVISIONAL",
            "expected_version": round.control_version,
            "evidence_digest": preview["evidence_digest"],
        },
    )
    published = approve_result(
        round.pk,
        reviewer,
        {
            "action_id": str(uuid.uuid4()),
            "reason": "Verified provisional coding",
            "proposal_id": provisional["proposal_id"],
        },
    )
    snapshot = ResultSnapshot.objects.get(pk=published["snapshot_id"])
    when = snapshot.appeal_deadline + timedelta(seconds=1)
    round.refresh_from_db()
    preview = build_preview(round, when)
    with patch("competition.results.database_now", return_value=when):
        final = propose_result(
            round.pk,
            maker,
            {
                "action_id": str(uuid.uuid4()),
                "reason": "Final coding results",
                "status": "FINAL",
                "expected_version": round.control_version,
                "evidence_digest": preview["evidence_digest"],
                "evidence_confirmed": True,
            },
        )
        outcome = approve_result(
            round.pk,
            reviewer,
            {
                "action_id": str(uuid.uuid4()),
                "reason": "Verified final coding",
                "proposal_id": final["proposal_id"],
                "evidence_confirmed": True,
            },
        )
    assert outcome["qualifier_codes"] == [teams[0].code]


def test_judging_cannot_use_unknown_tests_or_changed_source(coding):
    from competition.api import ApiProblem
    from competition.coding_results import propose_judgment

    submission = ended_bundle(coding)
    with pytest.raises(ApiProblem, match="fixed hidden tests"):
        propose_judgment(
            coding[0].pk, coding[3], grade_data(coding, submission, passed=["unknown"])
        )
    data = grade_data(coding, submission)
    data["grades"][0]["source_hash"] = "wrong-source"
    with pytest.raises(ApiProblem, match="frozen task version"):
        propose_judgment(coding[0].pk, coding[3], data)


def test_correct_task_count_precedes_final_time_in_coding_ranking(coding):
    from competition.coding_results import approve_judgment, propose_judgment
    from competition.results import build_preview

    round, tasks, teams, maker, reviewer = coding
    start(coding)
    for index in range(2):
        client = assigned_client(coding, index)
        for task_index in range(len(tasks)):
            assert save(coding, client, task=task_index)[0].status_code == 200
        assert (
            post(
                client,
                f"/api/rounds/{round.pk}/coding/finalize",
                {
                    "action_id": str(uuid.uuid4()),
                    "expected_revisions": {str(task.pk): 1 for task in tasks},
                },
            ).status_code
            == 200
        )
    round.refresh_from_db()
    control_round(
        round.pk,
        maker,
        {
            "action": "end",
            "action_id": str(uuid.uuid4()),
            "reason": "Rank coding test",
            "expected_version": round.control_version,
        },
    )
    for index in range(2):
        submission = CodingSubmission.objects.get(team=teams[index])
        data = grade_data(coding, submission, passed=["a"] if index == 0 else [])
        for task, grade in zip(tasks, data["grades"], strict=True):
            if task.category == "OUTPUT":
                grade["correct"] = index == 1
            if task.category == "LOGIC":
                grade["correct"] = False
        proposed = propose_judgment(round.pk, maker, data)
        approve_judgment(
            round.pk,
            reviewer,
            {
                "action_id": str(uuid.uuid4()),
                "proposal_id": proposed["judgment_proposal_id"],
                "reason": "Reviewed ranking evidence",
                "evidence_confirmed": True,
            },
        )
    round.refresh_from_db()
    preview = build_preview(round, timezone.now())
    assert preview["entries"][0]["team_code"] == teams[1].code
    assert [entry["score"] for entry in preview["entries"]] == [60, 60]
    assert [entry["fully_correct_tasks"] for entry in preview["entries"]] == [3, 2]


def test_exact_final_metric_ties_stay_blocked_without_an_approved_reserve_policy(coding):
    from competition.results import build_preview

    round, _, _, maker, _ = coding
    round.rules["qualification_tie_policy"] = "block_exact_ties"
    round.save()
    start(coding)
    control_round(
        round.pk,
        maker,
        {
            "action": "end",
            "action_id": str(uuid.uuid4()),
            "reason": "No work tie test",
            "expected_version": round.control_version,
        },
    )
    round.refresh_from_db()
    preview = build_preview(round, timezone.now())
    assert len(preview["cutoff_tie"]) == 2
    assert any(
        "exact score/task/time tie" in blocker for blocker in preview["finalization_blockers"]
    )


def test_rejudging_changed_marks_requires_a_revised_provisional_appeal_window(coding):
    from competition.coding_results import approve_judgment, propose_judgment
    from competition.results import approve_result, build_preview, propose_result

    round, _, _, maker, reviewer = coding
    submission = ended_bundle(coding)
    for index, passed in enumerate([["a"], ["a", "b"]]):
        proposal = propose_judgment(round.pk, maker, grade_data(coding, submission, passed=passed))
        approve_judgment(
            round.pk,
            reviewer,
            {
                "action_id": str(uuid.uuid4()),
                "proposal_id": proposal["judgment_proposal_id"],
                "reason": "Independent rerun review",
                "evidence_confirmed": True,
            },
        )
        round.refresh_from_db()
        if index == 0:
            preview = build_preview(round, timezone.now())
            pending = propose_result(
                round.pk,
                maker,
                {
                    "action_id": str(uuid.uuid4()),
                    "reason": "Initial coding publication",
                    "status": "PROVISIONAL",
                    "expected_version": round.control_version,
                    "evidence_digest": preview["evidence_digest"],
                },
            )
            approve_result(
                round.pk,
                reviewer,
                {
                    "action_id": str(uuid.uuid4()),
                    "reason": "Initial independent publication",
                    "proposal_id": pending["proposal_id"],
                },
            )
    preview = build_preview(round, timezone.now() + timedelta(hours=1))
    assert any("revised provisional coding" in item for item in preview["finalization_blockers"])


@pytest.mark.django_db(transaction=True)
def test_concurrent_coding_tabs_cannot_overwrite_the_same_response_revision(coding):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier

    from django.db import connections

    start(coding)
    original = assigned_client(coding)
    barrier = Barrier(2)

    def worker(number):
        try:
            client = Client(enforce_csrf_checks=True)
            client.cookies = original.cookies.copy()
            barrier.wait(timeout=10)
            return save(coding, client, body=f"Concurrent source {number}")[0].status_code
        finally:
            connections.close_all()

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(worker, [1, 2])) == [200, 409]
    assert CodingRevision.objects.count() == 1


def test_released_coding_tasks_cannot_move_into_a_new_draft_attempt(coding):
    ready(coding)
    task = coding[1][0]
    task.round = Round.objects.create(
        number=3, attempt_no=2, title="New draft", delivery_mode="CODING", is_demo=True
    )
    with pytest.raises(ValidationError, match="instead of moving"):
        task.save()


@pytest.mark.django_db(transaction=True)
@pytest.mark.skipif(
    os.environ.get("TTH_BROWSER_INTEGRATION") != "1",
    reason="Opt-in: Vite and Playwright Chromium required.",
)
def test_full_browser_coding_and_lab_review(coding, live_server):
    ready(coding)
    node = shutil.which("node")
    assert node is not None
    result = subprocess.run(
        [node, "frontend/scripts/live-coding-smoke.mjs"],
        cwd=Path(__file__).resolve().parents[2],
        env={
            **os.environ,
            "TTH_BACKEND_URL": live_server.url.replace("localhost", "127.0.0.1"),
            "TTH_CODING_ROUND": str(coding[0].pk),
        },
        capture_output=True,
        text=True,
        timeout=90,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    from competition.models import CodingJudgment

    assert CodingJudgment.objects.get().score == 15
    assert ResultSnapshot.objects.filter(round=coding[0], status="PROVISIONAL").count() == 1


def test_coding_seed_prepares_unverified_content_without_fabricating_qualification(
    coding, settings
):
    from io import StringIO

    from django.core.management import call_command

    settings.DEBUG = True
    round = coding[0]
    CodingTask.objects.filter(round=round).delete()
    previous_count = ResultSnapshot.objects.count()
    call_command("seed_coding_demo", actor=coding[3].username, stdout=StringIO())
    tasks = list(CodingTask.objects.filter(round=round))
    assert len(tasks) == 5 and all(task.verified_by_id is None for task in tasks)
    assert sum(task.points for task in tasks) == 100
    assert ResultSnapshot.objects.count() == previous_count
    round.refresh_from_db()
    before = round.rules
    call_command("seed_coding_demo", actor=coding[3].username, stdout=StringIO())
    round.refresh_from_db()
    assert round.rules == before and CodingTask.objects.filter(round=round).count() == 5
