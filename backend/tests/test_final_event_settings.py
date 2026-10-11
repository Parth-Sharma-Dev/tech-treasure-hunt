from io import StringIO

import pytest
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.core.management.base import CommandError

from competition.final_event_settings import ROUND1_RULES, ROUND2_RULES
from competition.models import Mission, Round

pytestmark = pytest.mark.django_db


@pytest.fixture
def event(settings):
    settings.PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]
    users = get_user_model()
    maker = users.objects.create_superuser(username="parth")
    verifier = users.objects.create_superuser(username="verifier")
    rounds = [
        Round.objects.create(number=n, title=f"Real {n}", delivery_mode=mode)
        for n, mode in ((1, "ONLINE_HUNT"), (2, "EXTERNAL"))
    ]
    return maker, verifier, rounds


def test_final_settings_map_real_staff_ids_and_preserve_draft_content(event):
    maker, verifier, rounds = event
    mission = Mission.objects.create(round=rounds[0], public_id="MISSION-01", hint="Private clue")
    call_command("configure_final_event", stdout=StringIO())
    r1, r2 = [Round.objects.get(pk=r.pk) for r in rounds]
    assert r1.rules == ROUND1_RULES and r2.rules == ROUND2_RULES
    assert (r1.advancement_count, r2.advancement_count) == (50, 20)
    assert r1.active_budget_ms == r2.active_budget_ms == 3600000
    assert r1.rules["appeal_minutes"] == r2.rules["appeal_minutes"] == 5
    assert r1.owners["adjudicator"] == maker.pk and r1.owners["verifier"] == verifier.pk
    assert r1.state == r2.state == "DRAFT" and not r1.approved_at
    mission.refresh_from_db()
    assert mission.hint == "Private clue" and not mission.verified_at


def test_final_settings_dry_run_and_released_refusal(event):
    _, _, rounds = event
    call_command("configure_final_event", dry_run=True, stdout=StringIO())
    assert Round.objects.get(pk=rounds[0].pk).rules == {}
    Round.objects.filter(pk=rounds[1].pk).update(state="READY")
    with pytest.raises(CommandError, match="DRAFT"):
        call_command("configure_final_event")
    assert Round.objects.get(pk=rounds[0].pk).rules == {}


def test_private_storage_probe_reads_back_and_removes_only_probe(event, settings, tmp_path):
    settings.STORAGES["mission_images"] = {
        "BACKEND": "competition.mission_images.PrivateFileStorage",
        "OPTIONS": {"location": tmp_path},
    }
    retained = tmp_path / "real-mission.png"
    retained.write_bytes(b"retained")
    output = StringIO()
    call_command("check_mission_storage", stdout=output)
    assert "write/read passed" in output.getvalue()
    assert retained.read_bytes() == b"retained"
    assert not list((tmp_path / "deployment-checks").glob("*.png"))
