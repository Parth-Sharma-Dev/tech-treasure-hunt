import base64
import hashlib
import json
import os
import zipfile
from io import StringIO

import pytest
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.core.management.base import CommandError
from django.utils import timezone

from competition.event_transfer import export_package, import_package
from competition.models import EventContentSource, FacultyProfile, HuntCode, Mission, Round, Team

pytestmark = pytest.mark.django_db


@pytest.fixture
def actor():
    return get_user_model().objects.create_superuser(
        username="transfer-maker", password="test-only"
    )


@pytest.fixture
def payload():
    raw = b"Private original code CSV\n"
    sha = hashlib.sha256(raw).hexdigest()
    key = f"1:CODE_POOL:{sha}"
    return {
        "version": "event-drafts-v1",
        "rounds": [
            {
                "number": n,
                "title": f"Synthetic round {n}",
                "delivery_mode": delivery,
                "rules_version": "test-v1",
                "rules": {"short_roster_policy": "advance_all_eligible"},
                "advancement_count": 3 if n < 5 else None,
                "active_budget_ms": 120000,
            }
            for n, delivery in enumerate(
                ["ONLINE_HUNT", "EXTERNAL", "CODING", "EXTERNAL", "BUZZER"], 1
            )
        ],
        "missions": [
            {
                "round": 1,
                "public_id": "MISSION-01",
                "token": "private-navigation-token",
                "fallback_code": "ABCDEFGH",
                "hint": "Private prepared riddle",
                "symbol": "",
                "clue_type": "TEXT",
                "qr_location": "",
                "clue_location": "Private location",
                "difficulty": "",
                "points": 1,
                "keyword": "",
                "is_practice": False,
            }
        ],
        "sources": [
            {
                "key": key,
                "round": 1,
                "kind": "CODE_POOL",
                "filename": "codes.csv",
                "sha256": sha,
                "content": {"count": 1},
                "original_base64": base64.b64encode(raw).decode(),
            }
        ],
        "codes": [{"round": 1, "source": key, "code": "A1!b2?", "keyword": "Fixed keyword"}],
        "faculty": [
            {
                "display_name": "Synthetic faculty",
                "role": "Faculty",
                "location": "",
                "contact_channel": "Private contact",
                "photo_url": "",
                "consent_reference": "",
            }
        ],
    }


def write_package(path, payload):
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("event.json", json.dumps(payload))
    return path


def test_transfer_preserves_accounts_roster_demo_and_navigation_and_keywords(
    tmp_path, actor, payload
):
    participant = get_user_model().objects.create_user(
        username="already-on-azure", password="private"
    )
    team = Team.objects.create(
        code="MOCK-A", name="Existing team", user=participant, member_count=3
    )
    demo = Round.objects.create(number=1, title="Retained demo", is_demo=True, state="FINALIZED")
    package = write_package(tmp_path / "content.zip", payload)
    original_password = participant.password
    summary = import_package(package, actor)
    assert summary["missions"] == summary["codes"] == 1
    mission = Mission.objects.get()
    assert mission.token == payload["missions"][0]["token"]
    assert mission.prepared_by == actor and not mission.available and not mission.verified_at
    assert HuntCode.objects.get().keyword == "Fixed keyword"
    assert bytes(EventContentSource.objects.get().original_bytes) == b"Private original code CSV\n"
    assert not FacultyProfile.objects.get().visible
    assert Round.objects.filter(is_demo=False, state="DRAFT").count() == 5
    assert all(not r.owners and not r.approved_by for r in Round.objects.filter(is_demo=False))
    participant.refresh_from_db()
    demo.refresh_from_db()
    assert participant.password == original_password
    assert Team.objects.get().pk == team.pk and demo.state == "FINALIZED"
    with pytest.raises(CommandError):
        import_package(package, actor)
    assert Mission.objects.count() == HuntCode.objects.count() == 1
    exported = export_package(tmp_path / "round-trip.zip")
    assert exported["missions"] == payload["missions"]
    assert exported["codes"] == payload["codes"]
    assert "users" not in exported and "owners" not in exported["rounds"][0]


def test_dry_run_preserves_empty_shells_and_all_database_records(tmp_path, actor, payload):
    shell = Round.objects.create(number=1, title="Synthetic round 1", attempt_no=2)
    summary = import_package(write_package(tmp_path / "content.zip", payload), actor, dry_run=True)
    assert summary["round_ids"][1] == shell.pk
    shell.refresh_from_db()
    assert shell.rules == {} and not Mission.objects.exists()
    assert Round.objects.count() == 1 and not FacultyProfile.objects.exists()


def test_checksum_failure_rolls_back_rounds_and_preserves_roster(tmp_path, actor, payload):
    payload["sources"][0]["sha256"] = "0" * 64
    with pytest.raises(CommandError, match="checksum"):
        import_package(write_package(tmp_path / "content.zip", payload), actor)
    assert not Round.objects.exists() and not EventContentSource.objects.exists()


@pytest.mark.parametrize("state", ["READY", "LIVE", "FINALIZED"])
def test_released_destination_is_never_overwritten(tmp_path, actor, payload, state):
    round = Round.objects.create(number=1, title="Existing", state=state)
    with pytest.raises(CommandError, match="unapproved"):
        import_package(write_package(tmp_path / "content.zip", payload), actor)
    round.refresh_from_db()
    assert round.state == state and round.title == "Existing"


def test_permission_check_and_private_console_output(tmp_path, actor, payload):
    package = write_package(tmp_path / "content.zip", payload)
    denied = get_user_model().objects.create_user(username="not-authorized", is_staff=True)
    with pytest.raises(CommandError):
        call_command(
            "transfer_event_drafts", import_content=True, file=str(package), actor=denied.username
        )
    output = StringIO()
    call_command(
        "transfer_event_drafts",
        import_content=True,
        file=str(package),
        actor=actor.username,
        dry_run=True,
        stdout=output,
    )
    assert "no records saved" in output.getvalue()
    assert "Fixed keyword" not in output.getvalue() and "Private contact" not in output.getvalue()


def test_export_requires_private_unused_drafts_and_preserves_existing_file(
    tmp_path, actor, payload
):
    import_package(write_package(tmp_path / "content.zip", payload), actor)
    path = tmp_path / "export.zip"
    export_package(path)
    original = path.read_bytes()
    with pytest.raises(FileExistsError):
        export_package(path)
    assert path.read_bytes() == original
    Round.objects.filter(number=1).update(approved_at=timezone.now(), approved_by=actor)
    with pytest.raises(CommandError, match="unapproved"):
        export_package(tmp_path / "released.zip")


@pytest.mark.skipif(
    not os.environ.get("TTH_EVENT_TRANSFER_PACKAGE"),
    reason="Opt-in: validate the private organizer package without printing its contents.",
)
def test_actual_private_package_imports_on_isolated_database(actor):
    summary = import_package(os.environ["TTH_EVENT_TRANSFER_PACKAGE"], actor)
    assert len(summary["round_ids"]) == 5
    assert summary["missions"] == 25 and summary["codes"] == 168 and summary["faculty"] == 5
    assert Mission.objects.filter(available=True).count() == 0
    assert Round.objects.exclude(state="DRAFT").count() == 0
