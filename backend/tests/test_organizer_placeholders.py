import pytest
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.core.management.base import CommandError

from competition.models import FacultyProfile, Round, RoundInformation

pytestmark = pytest.mark.django_db


def test_placeholder_seed_is_unpublished_idempotent_and_preserves_real_data(settings):
    settings.DEBUG = True
    maker = get_user_model().objects.create_superuser(username="placeholder-maker")
    draft = Round.objects.create(number=4, title="Demo interview", is_demo=True)
    real = Round.objects.create(number=4, attempt_no=2, title="Actual interview", is_demo=False)
    real_info = RoundInformation.objects.create(round=real, venue="Existing real venue")
    call_command("seed_organizer_placeholders", actor=maker.username)
    assert FacultyProfile.objects.count() == 6
    assert not FacultyProfile.objects.filter(is_demo=False).exists()
    assert not FacultyProfile.objects.exclude(published_at=None).exists()
    assert not FacultyProfile.objects.filter(visible=True).exists()
    assert all(
        not item.consent_reference and not item.photo_url for item in FacultyProfile.objects.all()
    )
    information = RoundInformation.objects.get(round=draft)
    assert information.scheduled_start is None and information.published_at is None
    profile = FacultyProfile.objects.first()
    profile.display_name = "Organizer supplied faculty name"
    profile.location = "Organizer edited this draft"
    profile.save()
    information.venue = "Organizer supplied venue"
    information.save()
    call_command("seed_organizer_placeholders", actor=maker.username)
    profile.refresh_from_db()
    information.refresh_from_db()
    real_info.refresh_from_db()
    assert FacultyProfile.objects.count() == 6
    assert profile.location == "Organizer edited this draft"
    assert profile.display_name == "Organizer supplied faculty name"
    assert information.venue == "Organizer supplied venue"
    assert real_info.venue == "Existing real venue"


def test_placeholder_seed_refuses_production_and_preserves_released_rounds(settings):
    maker = get_user_model().objects.create_superuser(username="placeholder-maker")
    settings.DEBUG = False
    with pytest.raises(CommandError, match="local DEBUG"):
        call_command("seed_organizer_placeholders", actor=maker.username)
    settings.DEBUG = True
    Round.objects.create(number=4, title="Released interview", is_demo=True, state="READY")
    call_command("seed_organizer_placeholders", actor=maker.username)
    assert not FacultyProfile.objects.exists() and not RoundInformation.objects.exists()
