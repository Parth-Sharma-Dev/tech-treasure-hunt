"""Optional browser + real Django HTTP + isolated PostgreSQL integration."""

import os
import shutil
import subprocess
from pathlib import Path

import pytest
from django.contrib.auth import get_user_model

from competition.answers import answer_digest
from competition.models import Completion, Mission, Round, SubmissionDecision, Team


@pytest.mark.django_db(transaction=True)
@pytest.mark.skipif(
    os.environ.get("TTH_BROWSER_INTEGRATION") != "1",
    reason="Opt-in: requires Vite on port 5173 and Playwright Chromium.",
)
def test_full_browser_gameplay(live_server, settings):
    settings.PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]
    get_user_model().objects.create_superuser(
        username="browser-controller", password="synthetic-test-only"
    )
    user = get_user_model().objects.create_user(
        username="browser-team", password="synthetic-test-only"
    )
    Team.objects.create(code="BROWSER-01", name="Synthetic browser team", user=user, member_count=3)
    round = Round.objects.create(number=1, title="Isolated browser hunt", active_budget_ms=120_000)
    mission = Mission.objects.create(
        round=round,
        public_id="BROWSER-M1",
        hint="Synthetic test: enter 0042.",
        keyword="START",
        qr_location="Fictional",
        clue_location="Fictional",
    )
    mission.answer_verifiers = [
        {"version": "test-v1", "digest": answer_digest(mission.pk, "test-v1", "0042")}
    ]
    mission.save()
    # Explicit synthetic test fixture; never approves or changes the application database.
    Round.objects.filter(pk=round.pk).update(
        state="READY",
        rules_version="test-v1",
        rules_snapshot={
            "rules": {
                "free_wrong_attempts": 5,
                "cooldown_seconds": [30, 60, 120, 240, 300],
                "team_answer_limit": 10,
                "team_answer_window_ms": 60_000,
            }
        },
    )
    node = shutil.which("node")
    assert node is not None
    root = Path(__file__).resolve().parents[2]
    result = subprocess.run(
        [node, "frontend/scripts/live-gameplay-smoke.mjs"],
        cwd=root,
        env={
            **os.environ,
            "TTH_BACKEND_URL": live_server.url.replace("localhost", "127.0.0.1"),
            "TTH_MISSION_TOKEN": mission.token,
        },
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert Completion.objects.count() == 1
    assert SubmissionDecision.objects.get().outcome == "accepted"
    round.refresh_from_db()
    assert round.state == "FROZEN"
