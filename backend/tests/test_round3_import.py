import base64
import hashlib
import json

import pytest
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.core.management.base import CommandError

from competition.models import (
    CodingTask,
    EventContentSource,
    FacultyProfile,
    Round,
    RoundInformation,
)

pytestmark = pytest.mark.django_db


@pytest.fixture
def content(tmp_path):
    users = get_user_model()
    users.objects.create_superuser(username="parth", password=None)
    users.objects.create_superuser(username="verifier", password=None)
    r3 = Round.objects.create(number=3, title="Crack the Code", is_demo=False)
    r4 = Round.objects.create(number=4, title="Faculty Interaction", is_demo=False)
    raw = b"Synthetic private original"
    tasks = []
    for index, (category, points) in enumerate(
        zip(["OUTPUT", "DEBUG", "FILL", "SHORT", "LOGIC"], [15, 25, 20, 30, 10], strict=True), 1
    ):
        tasks.append(
            {
                "public_id": f"Q{index}",
                "category": category,
                "points": str(points),
                "prompt": "Synthetic participant task",
                "starter_code": "",
                "version": "synthetic-v1",
                "languages": ["PYTHON"],
                "private_rubric": {"test_cases": [{"id": "hidden", "input": "1", "expected": "1"}]},
            }
        )
    bundle = {
        "version": 1,
        "instructions": "Synthetic public instructions",
        "source": {
            "filename": "synthetic.docx",
            "sha256": hashlib.sha256(raw).hexdigest(),
            "content_base64": base64.b64encode(raw).decode(),
        },
        "tasks": tasks,
    }
    path = tmp_path / "private.json"
    path.write_text(json.dumps(bundle), encoding="utf-8")
    return r3, r4, path


def run(path, **kwargs):
    call_command(
        "import_round3_content", bundle=str(path), actor="parth", verifier="verifier", **kwargs
    )


def test_dry_run_and_import_prepare_only_and_preserve_faculty(content):
    r3, r4, path = content
    faculty = FacultyProfile.objects.create(
        display_name="Synthetic faculty",
        role="Judge",
        consent_reference="Synthetic consent",
        photo_url="https://example.com/private.png",
    )
    run(path, dry_run=True)
    assert not CodingTask.objects.exists() and not EventContentSource.objects.exists()
    r3.refresh_from_db()
    assert r3.rules == {}
    run(path)
    r3.refresh_from_db()
    r4.refresh_from_db()
    faculty.refresh_from_db()
    assert r3.advancement_count == 11 and r3.active_budget_ms == 2700000
    assert r3.state == r4.state == "DRAFT"
    assert r3.approved_at is None and r4.approved_at is None
    assert CodingTask.objects.filter(round=r3, verified_at__isnull=True).count() == 5
    assert r4.advancement_count == 5
    assert r4.rules["score_schema"]["qualification_only"] is True
    assert "faculty_panels" not in r4.rules
    assert faculty.display_name == "Synthetic faculty"
    assert RoundInformation.objects.get(round=r3).published_at is None
    with pytest.raises(CommandError, match="already exist"):
        run(path)
    assert CodingTask.objects.count() == 5


def test_import_refuses_released_later_rounds(content):
    r3, r4, path = content
    r4.state = "READY"
    r4.save()
    with pytest.raises(CommandError, match="DRAFT"):
        run(path)
    assert not CodingTask.objects.exists()
    r3.refresh_from_db()
    assert r3.rules == {}


def test_corrupt_original_is_rejected(content):
    _, _, path = content
    bundle = json.loads(path.read_text())
    bundle["source"]["sha256"] = "0" * 64
    path.write_text(json.dumps(bundle))
    with pytest.raises(CommandError, match="checksum"):
        run(path)
    assert not CodingTask.objects.exists()
