import json
import runpy
from pathlib import Path

import pytest
from django.contrib.auth import get_user_model

from competition.buzzer_scoring_rules import PENALTY_CONTRACT
from competition.final_event_settings import COMMON
from competition.models import BuzzerQuestion, Round
from competition.rules import readiness_errors

pytestmark = pytest.mark.django_db
setup = runpy.run_path(
    str(Path(__file__).resolve().parents[2] / "tools" / "setup_round5_from_ppt.py")
)["setup"]


@pytest.fixture
def manifest(tmp_path):
    users = get_user_model().objects
    users.create_superuser(username="parth", password=None)
    users.create_superuser(username="verifier", password=None)
    round = Round.objects.create(number=5)
    rules = {
        **COMMON,
        "allowed_tools": ["Official buzzer"],
        "movement_policy": "Remain at venue",
        "delivery_instructions": "Wait for host GO",
        "ranking_policy": "round5_score_then_last_correct",
        "score_schema": dict(PENALTY_CONTRACT),
        "buzzer_order_policy": "database_receipt_time",
        "buzzer_latency_policy": "no_compensation",
        "buzzer_equal_time_policy": "staff_review_required",
        "buzzer_early_policy": "penalize_before_host_go",
        "offline_rules_reference": "Reviewed host handbook",
    }
    questions = [
        {
            "public_id": f"S{s}-Q{q}",
            "stage": s,
            "version": "test-v1",
            "source_reference": "PPT answer slide reference",
            "private_content": {
                "answer": "Private test answer",
                "presentation_reference": "Slide reference",
            },
        }
        for s in range(1, 6)
        for q in range(1, 6)
    ]
    path = tmp_path / "manifest.json"
    path.write_text(
        json.dumps({"source": {"sha256": "0" * 64}, "rules": rules, "questions": questions})
    )
    return round, path


def test_setup_fills_policies_but_never_fabricates_content_verification(manifest):
    round, path = manifest
    setup(path, dry_run=True)
    assert not BuzzerQuestion.objects.exists()
    round.refresh_from_db()
    assert round.rules == {}
    setup(path, dry_run=False)
    round.refresh_from_db()
    assert BuzzerQuestion.objects.count() == 25
    assert not BuzzerQuestion.objects.filter(verified_at__isnull=False).exists()
    assert round.state == "DRAFT" and round.approved_at is None
    errors = readiness_errors(round)
    assert errors and all("independent active-staff content verification" in e for e in errors)
    with pytest.raises(ValueError, match="already exist"):
        setup(path, dry_run=False)
    assert BuzzerQuestion.objects.count() == 25
