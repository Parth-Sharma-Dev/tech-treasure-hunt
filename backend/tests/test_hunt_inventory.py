import json

import pytest
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.core.management.base import CommandError

from competition.models import EventContentSource, HuntCode, Mission, Round

pytestmark = pytest.mark.django_db


def test_independent_inventory_exact_bytes_stable_keywords_and_atomic_conflicts(tmp_path):
    actor = get_user_model().objects.create_superuser(username="inventory-maker")
    round = Round.objects.create(number=1, title="QR Mission Hunt")
    original = tmp_path / "codes.csv"
    raw = b'code\r\n!Ab3@x\r\n"X,y;Z!"\r\n'
    original.write_bytes(raw)
    locations = tmp_path / "locations.json"
    locations.write_text(json.dumps(["First location", "Second location"]), encoding="utf-8")
    args = {
        "round": round.pk,
        "csv": str(original),
        "locations": str(locations),
        "actor": actor.username,
        "expected_count": 2,
    }
    call_command("import_hunt_inventory", **args)
    assert set(HuntCode.objects.values_list("code", flat=True)) == {"!Ab3@x", "X,y;Z!"}
    keywords = dict(HuntCode.objects.values_list("code", "keyword"))
    assert all(keywords.values())
    assert bytes(EventContentSource.objects.get(kind="CODE_POOL").original_bytes) == raw
    assert not Mission.objects.exclude(answer_verifiers=[]).exists()
    assert not Mission.objects.exclude(keyword="").exists()
    assert not Mission.objects.exclude(hint="").exists()
    call_command("import_hunt_inventory", **args)
    assert dict(HuntCode.objects.values_list("code", "keyword")) == keywords
    assert Mission.objects.count() == 2 and EventContentSource.objects.count() == 2
    source = EventContentSource.objects.get(kind="CODE_POOL")
    with pytest.raises(ValidationError):
        HuntCode.objects.create(round=round, source=source, code="!aB3@X")
    locations.write_text(json.dumps(["Wrong first location"]), encoding="utf-8")
    with pytest.raises(CommandError, match="conflicts"):
        call_command("import_hunt_inventory", **args)
    assert EventContentSource.objects.count() == 2
    original.write_text("code\n!Ab3@x\n!aB3@X\n", encoding="utf-8")
    with pytest.raises(CommandError, match="uniqueness"):
        call_command("import_hunt_inventory", **args)
    round.state = "READY"
    round.save()
    item = HuntCode.objects.first()
    item.keyword = "Changed after release"
    with pytest.raises(ValidationError, match="frozen"):
        item.save()
    with pytest.raises(CommandError, match="DRAFT"):
        call_command("import_hunt_inventory", **args)
