import csv
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest
from django.contrib.auth import get_user_model
from test_gameplay import game as _game
from test_independent_codes import pool_game

from competition.models import Completion, SubmissionDecision, Team, TeamSession

game = _game
SCRIPT = Path(__file__).resolve().parents[2] / "tools/load_deployment.py"


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize("submit", [False, True])
def test_authenticated_load_runner_and_idempotent_writes(game, live_server, tmp_path, submit):
    round, missions, _, _, _, codes = pool_game(game)
    path = tmp_path / "private.csv"
    with path.open("w", newline="", encoding="utf-8") as output:
        writer = csv.writer(output)
        writer.writerow(["Team ID", "Password", "Load Code"])
        for index in range(3):
            code = f"LOAD-{index}"
            user = get_user_model().objects.create_user(username=code, password="load-test-only9!")
            Team.objects.create(code=code, name="Synthetic", user=user, member_count=3)
            writer.writerow([code, "load-test-only9!", codes[index].code])
    report = tmp_path / "report.json"
    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--base-url",
            live_server.url.replace("localhost", "127.0.0.1"),
            "--credentials",
            str(path),
            "--round-id",
            str(round.pk),
            "--teams",
            "3",
            "--duration-seconds",
            "2",
            "--ramp-seconds",
            "0",
            "--poll-seconds",
            "0.1",
            "--mission-token",
            missions[0].token,
            "--confirm-isolated-database",
            "--report",
            str(report),
            *(["--submit"] if submit else []),
        ],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    data = json.loads(report.read_text())
    assert data["logged_in_teams"] == 3 and data["passed"]
    assert "load-test-only9!" not in result.stdout
    assert not TeamSession.objects.filter(
        team__code__startswith="LOAD-", revoked_at__isnull=True
    ).exists()
    assert Completion.objects.count() == SubmissionDecision.objects.count() == (3 if submit else 0)


def test_private_csv_validation_preserves_quoted_passwords_and_rejects_shared_load_codes(tmp_path):
    spec = importlib.util.spec_from_file_location("load_deployment", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    path = tmp_path / "private.csv"
    with path.open("w", newline="", encoding="utf-8") as output:
        writer = csv.writer(output)
        writer.writerow(["Team ID", "Password", "Load Code"])
        writer.writerow(["01", 'Private,test"only!', "ABC123"])
        writer.writerow(["02", "Different9!", "abc123"])
    rows = module.read_credentials(path, 2, False)
    assert rows[0]["Team ID"] == "01" and rows[0]["Password"] == 'Private,test"only!'
    with pytest.raises(ValueError, match="distinct"):
        module.read_credentials(path, 2, True)


@pytest.mark.django_db(transaction=True)
def test_wrong_round_id_stops_before_roster_ramp_and_logs_out_preflight(
    game, live_server, tmp_path
):
    round = game[0]
    path = tmp_path / "private.csv"
    with path.open("w", newline="", encoding="utf-8") as output:
        writer = csv.writer(output)
        writer.writerow(["Team ID", "Password"])
        for index in range(3):
            user = get_user_model().objects.create_user(
                username=f"PRE-{index}", password="preflight9!"
            )
            Team.objects.create(code=f"PRE-{index}", name="Synthetic", user=user, member_count=3)
            writer.writerow([f"PRE-{index}", "preflight9!"])
    report = tmp_path / "wrong-id.json"
    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--base-url",
            live_server.url.replace("localhost", "127.0.0.1"),
            "--credentials",
            str(path),
            "--round-id",
            "999999",
            "--teams",
            "3",
            "--duration-seconds",
            "2",
            "--ramp-seconds",
            "0",
            "--confirm-isolated-database",
            "--report",
            str(report),
        ],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 1
    data = json.loads(report.read_text())
    assert data["load_ramp_started"] is False
    assert data["preflight"]["abort_reason"] == "round_id_not_visible_to_team"
    assert data["preflight"]["visible_rounds"][0]["id"] == round.pk
    assert TeamSession.objects.filter(team__code__startswith="PRE-").count() == 1
    assert not TeamSession.objects.filter(
        team__code__startswith="PRE-", revoked_at__isnull=True
    ).exists()
    assert "preflight9!" not in result.stdout
