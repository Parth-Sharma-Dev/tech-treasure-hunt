import json
from concurrent.futures import ThreadPoolExecutor, TimeoutError
from threading import Event
from unittest.mock import MagicMock

import pytest
from django.contrib.admin import site
from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.management import call_command
from django.db import connections, transaction
from django.test import override_settings
from django.utils import timezone

from competition.admin import MissionAdmin, MissionForm
from competition.answers import answer_digest
from competition.models import AuditEvent, Mission, Round, Team
from competition.rules import approve_rules, mark_ready, readiness_errors

pytestmark = pytest.mark.django_db


@pytest.fixture
def configured_hunt():
    user_model = get_user_model()
    maker = user_model.objects.create_superuser(username="maker", password=None)
    verifier = user_model.objects.create_superuser(username="verifier", password=None)
    participant = user_model.objects.create_user(username="TEST-TEAM")
    Team.objects.create(code="TEST-TEAM", name="Test team", user=participant, member_count=3)
    rules = {
        "allowed_tools": ["test-only"],
        "movement_policy": "stay_together",
        "route_reference": "test-route",
        "accessibility_policy": "test-alternative",
        "qualification_tie_policy": "supervised_reserve_clue",
        "appeal_minutes": 10,
        "paper_attempt_policy": "one_per_team_mission_per_60_active_seconds",
        "unresolved_data_policy": "suspend_for_review",
        "retention_days": 30,
        "delivery_instructions": "test-only",
        "ranking_policy": "score_then_last_active_completion",
        "points_per_mission": 1,
        "max_team_sessions": 1,
        "answer_format": "four_ascii_digits",
        "free_wrong_attempts": 5,
        "cooldown_seconds": [30, 60, 120, 240, 300],
        "team_answer_limit": 10,
        "team_answer_window_ms": 60_000,
        "cutoff_policy": "database_admission_no_grace",
        "registration_cap": 1,
        "peak_browser_count": 4,
        "expected_mission_count": 1,
    }
    round = Round.objects.create(
        number=1,
        title="Test hunt",
        delivery_mode=Round.Delivery.ONLINE_HUNT,
        rules_version="test-v1",
        rules=rules,
        advancement_count=1,
        owners={
            "technical_lead": maker.pk,
            "content_lead": maker.pk,
            "operations_lead": maker.pk,
            "adjudicator": maker.pk,
            "verifier": verifier.pk,
        },
    )
    mission = Mission.objects.create(
        round=round,
        public_id="TEST-M01",
        hint="Synthetic hint",
        keyword="TEST",
        qr_location="Test location",
        clue_location="Test location",
        prepared_by=maker,
        volunteer_owner=maker,
        verified_by=verifier,
        verified_at=timezone.now(),
        answer_verifiers=[{"version": "test-v1", "digest": "a" * 64}],
    )
    return round, mission, maker, verifier


def test_ready_requires_approval_and_freezes_complete_snapshot(configured_hunt):
    round, _, maker, verifier = configured_hunt
    assert readiness_errors(round) == []
    with pytest.raises(ValidationError, match="approval"):
        mark_ready(round.pk, maker)
    approve_rules(round.pk, verifier)
    ready = mark_ready(round.pk, maker)
    assert ready.state == Round.State.READY
    assert ready.rules_snapshot["advancement_count"] == 1
    assert ready.rules_digest == ready.approval_digest
    assert ready.rules_snapshot["rules"] == round.rules
    assert AuditEvent.objects.filter(action="round_ready").count() == 1
    mark_ready(round.pk, maker)
    assert AuditEvent.objects.filter(action="round_ready").count() == 1


def test_changes_after_approval_require_new_signature(configured_hunt):
    round, _, maker, verifier = configured_hunt
    round = approve_rules(round.pk, verifier)
    round.rules["allowed_tools"] = ["changed-policy"]
    round.save()
    with pytest.raises(ValidationError, match="approval"):
        mark_ready(round.pk, maker)
    assert Round.objects.get(pk=round.pk).state == Round.State.DRAFT


def test_released_rules_and_missions_cannot_be_edited(configured_hunt):
    round, mission, maker, verifier = configured_hunt
    approve_rules(round.pk, verifier)
    round = mark_ready(round.pk, maker)
    round.advancement_count = 2
    with pytest.raises(ValidationError, match="frozen"):
        round.save()
    mission.hint = "Replacement content"
    with pytest.raises(ValidationError, match="frozen"):
        mission.save()
    with pytest.raises(ValidationError, match="cannot be deleted"):
        mission.delete()


@pytest.mark.parametrize(
    "missing", ["advancement_count", "owners", "delivery_mode", "rules_version"]
)
def test_ready_rejects_missing_configuration(configured_hunt, missing):
    round, _, maker, _ = configured_hunt
    setattr(
        round,
        missing,
        None if missing == "advancement_count" else {} if missing == "owners" else "",
    )
    round.save()
    with pytest.raises(ValidationError):
        mark_ready(round.pk, maker)


def test_ready_rejects_unverified_or_self_verified_missions(configured_hunt):
    round, mission, _, verifier = configured_hunt
    mission.verified_at = None
    mission.save()
    with pytest.raises(ValidationError, match="verification"):
        approve_rules(round.pk, verifier)
    mission.verified_at = timezone.now()
    mission.verified_by = mission.prepared_by
    mission.save()
    with pytest.raises(ValidationError, match="independent verifier"):
        approve_rules(round.pk, verifier)


def test_ready_needs_explicit_short_roster_decision(configured_hunt):
    round, _, _, _ = configured_hunt
    round.advancement_count = 2
    assert any("short-roster" in error for error in readiness_errors(round))
    round.rules["short_roster_policy"] = "advance_all_eligible"
    assert not any("short-roster" in error for error in readiness_errors(round))


def test_editing_draft_content_invalidates_previous_verification(configured_hunt):
    round, mission, _, verifier = configured_hunt
    mission.hint = "Different clue requiring a fresh independent check"
    mission.save(update_fields=["hint"])
    mission.refresh_from_db()
    assert mission.verified_by is None
    assert mission.verified_at is None
    with pytest.raises(ValidationError, match="verification"):
        approve_rules(round.pk, verifier)


def test_participant_cannot_approve_or_release_rules(configured_hunt):
    round, _, _, _ = configured_hunt
    participant = Team.objects.get(code="TEST-TEAM").user
    with pytest.raises(PermissionDenied):
        approve_rules(round.pk, participant)
    with pytest.raises(PermissionDenied):
        mark_ready(round.pk, participant)


def test_paper_mode_cannot_reopen_online_scoring(configured_hunt):
    round, _, _, _ = configured_hunt
    round.play_mode = Round.PlayMode.PAPER
    round.save()
    round.play_mode = Round.PlayMode.ONLINE
    with pytest.raises(ValidationError, match="cannot reopen"):
        round.save()


@pytest.mark.django_db(transaction=True)
def test_ready_lock_prevents_waiting_content_edit_from_crossing_release(configured_hunt):
    round, mission, maker, verifier = configured_hunt
    approve_rules(round.pk, verifier)
    started = Event()

    def edit_content():
        try:
            candidate = Mission.objects.get(pk=mission.pk)
            candidate.hint = "Racing edit"
            started.set()
            try:
                candidate.save()
            except ValidationError as error:
                return error
        finally:
            connections.close_all()

    with ThreadPoolExecutor(max_workers=1) as pool:
        with transaction.atomic():
            Round.objects.select_for_update().get(pk=round.pk)
            editing = pool.submit(edit_content)
            assert started.wait(timeout=5)
            with pytest.raises(TimeoutError):
                editing.result(timeout=0.1)
            mark_ready(round.pk, maker)
        assert isinstance(editing.result(timeout=5), ValidationError)
    mission.refresh_from_db()
    assert mission.hint == "Synthetic hint"


def test_admin_blocks_posting_changes_to_released_rules_and_original_evidence(
    client, configured_hunt
):
    round, mission, maker, verifier = configured_hunt
    approve_rules(round.pk, verifier)
    round = mark_ready(round.pk, maker)
    client.force_login(maker)
    assert client.get(f"/admin/competition/round/{round.pk}/change/").status_code == 200
    assert client.get(f"/admin/competition/mission/{mission.pk}/change/").status_code == 200
    response = client.post(
        f"/admin/competition/round/{round.pk}/change/", {"title": "Unauthorized edit"}
    )
    assert response.status_code == 403
    audit = AuditEvent.objects.get(action="round_ready")
    response = client.post(
        f"/admin/competition/auditevent/{audit.pk}/change/", {"reason": "Rewrite history"}
    )
    assert response.status_code == 403
    round.refresh_from_db()
    assert round.title == "Test hunt"


@override_settings(ANSWER_HMAC_KEY="test-only-key")
def test_admin_stores_only_a_verifier_for_the_four_digit_answer(configured_hunt):
    round, _, maker, _ = configured_hunt
    answer = MissionForm.base_fields["answer"].clean("0427")
    mission = Mission(
        round=round,
        public_id="TEST-M02",
        hint="Another synthetic clue",
        keyword="TEST",
        qr_location="Test location",
        clue_location="Test location",
        volunteer_owner=maker,
    )
    model_admin = MissionAdmin(Mission, site)
    request = MagicMock(user=maker)
    form = MagicMock(cleaned_data={"answer": answer})
    model_admin.save_model(request, mission, form, change=False)
    mission.refresh_from_db()
    verifier = mission.answer_verifiers[0]
    assert verifier["digest"] == answer_digest(mission.pk, verifier["version"], "0427")
    assert set(verifier) == {"version", "digest"}
    assert mission.verified_by is None


@override_settings(ANSWER_HMAC_KEY="test-only-key")
def test_answer_digests_preserve_leading_zeros_and_bind_mission_and_version():
    digest = answer_digest(1, "v1", "0427")
    assert len(digest) == 64
    assert digest != answer_digest(2, "v1", "0427")
    assert digest != answer_digest(1, "v2", "0427")
    for invalid in (427, "427", "４２７０", "0427\n", " 0427"):
        with pytest.raises(ValidationError):
            answer_digest(1, "v1", invalid)


@override_settings(DEBUG=True, ANSWER_HMAC_KEY="test-only-key")
def test_demo_seed_is_repeatable_unsigned_and_does_not_reset_passwords(tmp_path):
    credentials_path = tmp_path / "demo-credentials.json"
    call_command("seed_demo", credentials_file=str(credentials_path))
    password_before = get_user_model().objects.get(username="DEMO-01").password
    credentials_before = json.loads(credentials_path.read_text())
    call_command("seed_demo", credentials_file=str(credentials_path))
    assert Round.objects.count() == 5
    assert Team.objects.count() == 2
    assert Mission.objects.count() == 3
    assert not Round.objects.exclude(state=Round.State.DRAFT).exists()
    assert not Round.objects.exclude(approved_by=None).exists()
    assert not Mission.objects.exclude(verified_at=None).exists()
    assert get_user_model().objects.get(username="DEMO-01").password == password_before
    assert json.loads(credentials_path.read_text()) == credentials_before
