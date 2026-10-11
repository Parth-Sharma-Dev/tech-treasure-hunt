import hashlib
import importlib
from io import BytesIO
from unittest.mock import MagicMock

import pytest
from django.apps import apps
from django.contrib import admin
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.forms.models import model_to_dict
from django.test import Client
from django.utils import timezone
from PIL import Image, PngImagePlugin
from test_rules import configured_hunt as _configured_hunt

from competition.admin import MissionAdmin, MissionForm
from competition.evidence import export_objects, inventory
from competition.mission_images import PrivateFileStorage, normalize_upload, verified_image_bytes
from competition.models import Mission, Round
from competition.rules import approve_rules, mark_ready, readiness_errors, round_snapshot

configured_hunt = _configured_hunt
pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def image_storage(tmp_path, monkeypatch):
    storage = PrivateFileStorage(location=tmp_path / "images")
    monkeypatch.setattr(Mission._meta.get_field("clue_image"), "storage", storage)
    return storage


def upload(size=(80, 50)):
    stream = BytesIO()
    metadata = PngImagePlugin.PngInfo()
    metadata.add_text("secret", "private-original-metadata")
    Image.new("RGB", size, color="green").save(stream, "PNG", pnginfo=metadata)
    return SimpleUploadedFile(
        "private-source-name.png", stream.getvalue(), content_type="image/png"
    )


def attach(mission):
    image = normalize_upload(upload())
    mission.clue_type = "IMAGE"
    mission.clue_image = image["file"]
    mission.image_sha256 = image["sha256"]
    mission.image_width, mission.image_height = image["width"], image["height"]
    mission.image_alt = "A green symbol, described without giving the answer."
    mission.save()
    return mission


def test_upload_reencodes_strips_metadata_and_uses_private_storage(configured_hunt):
    _, mission, _, _ = configured_hunt
    attach(mission)
    data = verified_image_bytes(mission)
    with Image.open(BytesIO(data)) as image:
        assert image.size == (80, 50)
        assert "secret" not in image.info
    assert "private-source-name" not in mission.clue_image.name
    assert hashlib.sha256(data).hexdigest() == mission.image_sha256
    with pytest.raises(ValueError, match="authorized"):
        _ = mission.clue_image.url


@pytest.mark.parametrize("content", [b"not an image", b'<svg xmlns="http://www.w3.org/2000/svg"/>'])
def test_rejects_fake_images_and_svg(content):
    with pytest.raises(ValidationError, match="valid"):
        normalize_upload(SimpleUploadedFile("clue.png", content, content_type="image/png"))


def test_rejects_oversized_file_and_pixel_dimensions():
    with pytest.raises(ValidationError, match="5 MiB"):
        normalize_upload(SimpleUploadedFile("large.png", b"x" * (5 * 1024 * 1024 + 1)))
    with pytest.raises(ValidationError, match="4096"):
        normalize_upload(upload(size=(4097, 1)))


def test_image_change_invalidates_verification_and_ready_freezes_image(configured_hunt):
    round, mission, maker, verifier = configured_hunt
    attach(mission)
    mission.refresh_from_db()
    assert mission.verified_at is None
    mission.verified_by, mission.verified_at = verifier, timezone.now()
    mission.save()
    approve_rules(round.pk, verifier)
    assert round_snapshot(round)["mission_images"][0]["image_sha256"] == mission.image_sha256
    mark_ready(round.pk, maker)
    mission.image_alt = "Changed after release"
    with pytest.raises(ValidationError, match="frozen"):
        mission.save()


def test_missing_image_or_alternative_text_blocks_readiness(configured_hunt):
    round, mission, _, _ = configured_hunt
    mission.clue_type = "IMAGE"
    mission.save()
    assert any("uploaded clue image" in error for error in readiness_errors(round))
    attach(mission)
    mission.image_alt = ""
    mission.save()
    assert any("alternative text" in error for error in readiness_errors(round))


def test_verifier_checks_stored_bytes_and_draft_removal_clears_image(configured_hunt):
    _, mission, maker, verifier = configured_hunt
    attach(mission)
    mission.prepared_by = maker
    mission.save()
    desk = MissionAdmin(Mission, admin.site)
    desk.message_user = MagicMock()
    desk.verify_selected_missions(MagicMock(user=verifier), Mission.objects.filter(pk=mission.pk))
    mission.refresh_from_db()
    assert mission.verified_by == verifier
    with mission.clue_image.open("wb") as stream:
        stream.write(b"tampered storage bytes")
    desk.verify_selected_missions(MagicMock(user=verifier), Mission.objects.filter(pk=mission.pk))
    assert "checksum" in str(desk.message_user.call_args)


def test_image_reference_and_hash_survive_signed_export_and_legacy_inventory(configured_hunt):
    round, mission, _, _ = configured_hunt
    objects = export_objects(round)
    item = next(item for item in objects if item["model"] == "competition.mission")
    old = {
        **item,
        "fields": {
            key: value
            for key, value in item["fields"].items()
            if not key.startswith("image_") and key not in {"clue_type", "clue_image"}
        },
    }
    assert inventory([old]) == inventory([item])
    attach(mission)
    updated = next(item for item in export_objects(round) if item["model"] == "competition.mission")
    assert updated["fields"]["image_sha256"] == mission.image_sha256
    assert updated["fields"]["clue_image"] == mission.clue_image.name
    assert inventory([updated]) != inventory([old])


def test_admin_form_uploads_and_removes_image_without_changing_riddle_data(configured_hunt):
    _, mission, maker, _ = configured_hunt
    data = model_to_dict(mission, exclude=["answer_verifiers"])
    data.update(clue_type="IMAGE", image_alt="Approved visual description")
    form = MissionForm(data, {"upload_image": upload()}, instance=mission)
    assert form.is_valid(), form.errors
    desk = MissionAdmin(Mission, admin.site)
    desk.save_model(MagicMock(user=maker), form.save(commit=False), form, change=True)
    mission.refresh_from_db()
    assert mission.image_sha256 and mission.clue_image
    assert mission.hint == "Synthetic hint"
    data = model_to_dict(mission, exclude=["answer_verifiers"])
    data.update(clear_image=True, available=False)
    form = MissionForm(data, instance=mission)
    assert form.is_valid(), form.errors
    desk.save_model(MagicMock(user=maker), form.save(commit=False), form, change=True)
    mission.refresh_from_db()
    assert not mission.clue_image and not mission.image_sha256 and mission.image_width == 0


def test_migration_marks_only_remaining_draft_placeholders(configured_hunt):
    round, mission, _, _ = configured_hunt
    placeholder = Mission.objects.create(round=round, public_id="MISSION-14", available=False)
    released = Round.objects.create(
        number=1, attempt_no=2, title="Retained released attempt", state="READY"
    )
    retained = Mission.objects.create(round=round, public_id="MISSION-15", available=False)
    # Simulate an old released row without invoking current draft-only creation guards.
    Mission.objects.filter(pk=retained.pk).update(round=released)
    migration = importlib.import_module("competition.migrations.0022_mission_image_clues")
    migration.mark_remaining_image_placeholders(apps, None)
    placeholder.refresh_from_db()
    retained.refresh_from_db()
    mission.refresh_from_db()
    assert placeholder.clue_type == "IMAGE"
    assert retained.clue_type == mission.clue_type == "TEXT"


def test_admin_preview_is_private_and_redacts_storage_failure(configured_hunt):
    _, mission, maker, _ = configured_hunt
    attach(mission)
    path = f"/api/staff/missions/{mission.pk}/image"
    client = Client()
    assert client.get(path).status_code == 403
    client.force_login(maker)
    response = client.get(path)
    assert response.status_code == 200 and response["Content-Type"] == "image/png"
    assert response["Cache-Control"] == "no-store"
    mission.clue_image.storage.delete(mission.clue_image.name)
    response = client.get(path)
    assert response.status_code == 503
    assert mission.clue_image.name not in response.content.decode()
