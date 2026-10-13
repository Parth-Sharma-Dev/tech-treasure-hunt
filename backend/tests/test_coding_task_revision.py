import hashlib
import json
import runpy
from pathlib import Path

import pytest
from django.contrib.auth import get_user_model
from django.utils import timezone

from competition.models import CodingTask, EventContentSource, Round

pytestmark = pytest.mark.django_db
apply_revision = runpy.run_path(
    str(Path(__file__).resolve().parents[2] / "tools" / "revise_coding_task.py")
)["apply_revision"]


@pytest.fixture
def revision(tmp_path):
    actor = get_user_model().objects.create_superuser(username="revision-maker", password=None)
    reviewer = get_user_model().objects.create_superuser(
        username="revision-reviewer", password=None
    )
    round = Round.objects.create(number=3, delivery_mode="CODING", is_demo=False)
    task = CodingTask.objects.create(
        round=round,
        public_id="Q1",
        category="OUTPUT",
        points=15,
        languages=["TEXT"],
        prompt="Original question",
        version="v1",
        private_rubric={"expected": "original"},
        prepared_by=actor,
        verified_by=reviewer,
        verified_at=timezone.now(),
    )
    data = {
        "public_id": "Q1",
        "expected_prompt_sha256": hashlib.sha256(task.prompt.encode()).hexdigest(),
        "prompt": "Replacement reasoning question",
        "version": "v2",
        "private_rubric": {"expected": "new reasoning"},
    }
    path = tmp_path / "revision.json"
    path.write_text(json.dumps(data))
    return actor, round, task, path


def test_revision_is_draft_only_clears_approval_and_preserves_marks(revision):
    actor, round, task, path = revision
    assert "rolled back" in apply_revision(path, actor.username, dry_run=True)
    task.refresh_from_db()
    assert task.version == "v1" and task.verified_at is not None
    assert not EventContentSource.objects.exists()
    apply_revision(path, actor.username)
    task.refresh_from_db()
    assert task.version == "v2" and task.verified_at is None and task.verified_by is None
    assert task.points == 15 and task.category == "OUTPUT" and task.languages == ["TEXT"]
    assert "already applied" in apply_revision(path, actor.username)
    assert EventContentSource.objects.count() == 1
    round.state = "READY"
    round.save()
    with pytest.raises(ValueError, match="DRAFT"):
        apply_revision(path, actor.username)


def test_revision_does_not_overwrite_an_organizer_edit(revision):
    actor, _, task, path = revision
    task.prompt = "Organizer edit"
    task.save()
    with pytest.raises(ValueError, match="overwrite"):
        apply_revision(path, actor.username)
    task.refresh_from_db()
    assert task.prompt == "Organizer edit"
    assert not EventContentSource.objects.exists()
