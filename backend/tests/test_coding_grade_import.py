import hashlib
import json
import runpy
from pathlib import Path

import pytest
from django.contrib.auth import get_user_model
from django.utils import timezone

from competition.coding_content import tasks_snapshot
from competition.models import (
    CodingJudgment,
    CodingJudgmentProposal,
    CodingSubmission,
    CodingTask,
    Round,
    Team,
)
from competition.results import digest

pytestmark = pytest.mark.django_db
import_grades = runpy.run_path(
    str(Path(__file__).resolve().parents[2] / "tools" / "import_coding_grades.py")
)["import_grades"]


@pytest.fixture
def report(tmp_path):
    users = get_user_model()
    maker = users.objects.create_superuser(username="grade-maker", password=None)
    reviewer = users.objects.create_superuser(username="grade-reviewer", password=None)
    team = Team.objects.create(
        code="SYNTHETIC",
        name="Synthetic",
        member_count=4,
        user=users.objects.create_user(username="synthetic-team"),
    )
    round = Round.objects.create(number=3, delivery_mode="CODING", advancement_count=11)
    task = CodingTask.objects.create(
        round=round,
        public_id="Q1",
        category="OUTPUT",
        points=15,
        languages=["TEXT"],
        version="synthetic-v1",
        prompt="Synthetic prompt",
        private_rubric={"expected": "synthetic"},
        prepared_by=maker,
        verified_by=reviewer,
        verified_at=timezone.now(),
    )
    round.rules_snapshot = {"coding_tasks": tasks_snapshot(round), "advancement_count": 11}
    round.state = "ENDED"
    round.save()
    manifest = [
        {
            "task_id": task.pk,
            "revision_id": 1,
            "revision": 1,
            "source_hash": hashlib.sha256(b"synthetic").hexdigest(),
            "language": "TEXT",
        }
    ]
    submission = CodingSubmission.objects.create(
        round=round,
        team=team,
        kind="MANUAL",
        submitted_at=timezone.now(),
        active_elapsed_ms=1000,
        manifest=manifest,
        manifest_digest=digest(manifest),
        workstation_evidence={"id": 1, "supervisor_id": maker.pk},
    )
    grades = [
        {
            "task_id": task.pk,
            "task_version": task.version,
            "source_hash": manifest[0]["source_hash"],
            "correct": True,
        }
    ]
    path = tmp_path / "report.json"
    path.write_text(
        json.dumps(
            {
                "round_id": round.pk,
                "cut": 11,
                "teams": [
                    {
                        "submission_id": submission.pk,
                        "team_code": team.code,
                        "submitted_at": submission.submitted_at.isoformat(),
                        "suggested_task_grades": grades,
                        "score": 15,
                        "fully_correct_tasks": 1,
                    }
                ],
            }
        )
    )
    return path, maker, reviewer


def test_bulk_import_independent_review_and_retries(report):
    path, maker, reviewer = report
    for _ in range(2):
        import_grades(path, "propose", maker.username, maker.username)
    assert CodingJudgmentProposal.objects.count() == 1
    assert not CodingJudgment.objects.exists()
    with pytest.raises(ValueError, match="different verifier"):
        import_grades(path, "approve", maker.username, maker.username, True)
    with pytest.raises(ValueError, match="confirm"):
        import_grades(path, "approve", reviewer.username, maker.username)
    for _ in range(2):
        import_grades(path, "approve", reviewer.username, maker.username, True)
    assert CodingJudgment.objects.count() == 1
    assert CodingJudgment.objects.get().score == 15


def test_corrupt_total_rolls_back_entire_import(report):
    path, maker, _ = report
    data = json.loads(path.read_text())
    data["teams"][0]["score"] = 100
    path.write_text(json.dumps(data))
    with pytest.raises(ValueError, match="totals"):
        import_grades(path, "propose", maker.username, maker.username)
    assert not CodingJudgmentProposal.objects.exists()
