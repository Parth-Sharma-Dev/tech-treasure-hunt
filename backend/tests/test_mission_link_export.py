import csv
import importlib.util
from pathlib import Path

import pytest
from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied
from django.core.management.base import CommandError

from competition.models import Mission, Round

pytestmark = pytest.mark.django_db


@pytest.fixture
def exporter():
    path = Path(__file__).resolve().parents[2] / "tools/export_mission_links.py"
    spec = importlib.util.spec_from_file_location("mission_link_export", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.export_links


def test_exports_real_competitive_navigation_without_private_clues_or_mutation(exporter, tmp_path):
    actor = get_user_model().objects.create_superuser(username="parth")
    round = Round.objects.create(number=1, title="Real hunt")
    mission = Mission.objects.create(
        round=round,
        public_id="MISSION-01",
        hint="PRIVATE RIDDLE",
        clue_location="PRIVATE ANSWER",
        keyword="PRIVATE KEYWORD",
        available=False,
        prepared_by=actor,
    )
    Mission.objects.create(round=round, public_id="PRACTICE", is_practice=True)
    output = tmp_path / "links.csv"
    _, count, warnings = exporter("https://example.test/", round.pk, actor.username, output)
    with output.open(encoding="utf-8-sig", newline="") as stream:
        rows = list(csv.DictReader(stream))
    assert count == 1 and rows[0] == {
        "mission_id": "MISSION-01",
        "mission_url": f"https://example.test/missions/{mission.token}",
        "fallback_code": mission.fallback_code,
    }
    assert warnings == {"unavailable": 1, "unverified": 1, "voided": 0}
    assert "PRIVATE" not in output.read_text(encoding="utf-8-sig")
    mission.refresh_from_db()
    assert not mission.available and mission.hint == "PRIVATE RIDDLE"
    with pytest.raises(FileExistsError):
        exporter("https://example.test", round.pk, actor.username, output)


@pytest.mark.parametrize(
    "url",
    [
        "http://example.test",
        "https://user:password@example.test",
        "https://example.test/path",
        "https://example.test?secret=x",
    ],
)
def test_rejects_unsafe_base_urls(exporter, tmp_path, url):
    with pytest.raises(CommandError, match="HTTPS"):
        exporter(url, 1, "parth", tmp_path / "links.csv")


def test_requires_content_role_and_real_round1(exporter, tmp_path):
    actor = get_user_model().objects.create_user(username="participant")
    with pytest.raises(PermissionDenied):
        exporter("https://example.test", 1, actor.username, tmp_path / "links.csv")
    actor.is_staff = actor.is_superuser = True
    actor.save()
    demo = Round.objects.create(number=1, title="Demo", is_demo=True)
    with pytest.raises(CommandError, match="real Round 1"):
        exporter("https://example.test", demo.pk, actor.username, tmp_path / "links.csv")
