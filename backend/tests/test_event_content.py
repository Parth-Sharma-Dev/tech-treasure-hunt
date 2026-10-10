import hashlib
import json

import pytest
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.core.management.base import CommandError

from competition.models import EventContentSource, FacultyProfile, Mission, Round

pytestmark = pytest.mark.django_db


def test_private_import_preserves_demo_and_edits_and_stores_no_answers(tmp_path):
    actor = get_user_model().objects.create_superuser(username="event-maker")
    demo = Round.objects.create(number=1, title="Retained demo", is_demo=True, state="FINALIZED")
    original = tmp_path / "synthetic.pdf"
    original.write_bytes(b"synthetic original")
    manifest = tmp_path / "manifest.json"
    payload = {
        "sources": [
            {
                "path": str(original),
                "round": 1,
                "kind": "RIDDLES",
                "sha256": hashlib.sha256(original.read_bytes()).hexdigest(),
                "content": {
                    "missions": [
                        {
                            "public_id": "MISSION-01",
                            "riddle": "Find the quiet place.",
                            "location": "Private location key",
                        }
                    ]
                },
            }
        ],
        "faculty": [{"name": "Synthetic faculty", "phone": "0000000000"}],
    }
    manifest.write_text(json.dumps(payload), encoding="utf-8")
    call_command("import_event_content", manifest=str(manifest), actor=actor.username)
    mission = Mission.objects.get()
    assert mission.hint == "Find the quiet place."
    assert not mission.keyword and not mission.answer_verifiers and not mission.available
    assert not mission.verified_at and not mission.round.is_demo
    assert mission.round.state == "DRAFT"
    source = EventContentSource.objects.get()
    assert bytes(source.original_bytes) == original.read_bytes()
    faculty = FacultyProfile.objects.get()
    assert not faculty.visible and not faculty.published_at and not faculty.consent_reference
    mission.hint = "Organizer edited riddle"
    mission.save()
    call_command("import_event_content", manifest=str(manifest), actor=actor.username)
    mission.refresh_from_db()
    demo.refresh_from_db()
    assert mission.hint == "Organizer edited riddle"
    assert demo.title == "Retained demo" and demo.state == "FINALIZED"
    assert Round.objects.filter(is_demo=False).count() == 5
    assert (
        Mission.objects.count()
        == EventContentSource.objects.count()
        == FacultyProfile.objects.count()
        == 1
    )
    original.write_bytes(b"changed original")
    with pytest.raises(CommandError, match="changed after extraction"):
        call_command("import_event_content", manifest=str(manifest), actor=actor.username)
    payload["sources"][0]["sha256"] = hashlib.sha256(original.read_bytes()).hexdigest()
    manifest.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(CommandError, match="different original"):
        call_command("import_event_content", manifest=str(manifest), actor=actor.username)
    assert EventContentSource.objects.count() == 1
