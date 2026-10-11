import csv
import json
from io import StringIO

import pytest
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.core.management.base import CommandError

from competition.api import ApiProblem
from competition.models import AuditEvent, Round, Team
from competition.team_import import HEADERS, import_teams

pytestmark = pytest.mark.django_db


@pytest.fixture
def staff(settings):
    settings.PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]
    users = get_user_model()
    return users.objects.create_superuser(username="parth"), users.objects.create_superuser(
        username="verifier"
    )


def source(tmp_path, count=110, change=None):
    path = tmp_path / "private.csv"
    with path.open("w", encoding="utf-8", newline="") as output:
        writer = csv.writer(output)
        writer.writerow(HEADERS)
        for index in range(count):
            row = [
                f"OFF-{index:03}",
                "Synthetic leader",
                f"leader{index}@example.test",
                "Synthetic9!Secret",
            ]
            if change and index == count - 1:
                row = change(row)
            writer.writerow(row)
    return path


def test_import_110_real_teams_hashes_passwords_emails_and_preserves_staff_demo(staff, tmp_path):
    maker, verifier = staff
    Round.objects.create(number=1, title="Real", state="DRAFT")
    user = get_user_model().objects.create_user(username="retained-demo", password="demo-only")
    demo = Team.objects.create(
        code="DEMO-01", name="Retained", user=user, member_count=3, is_demo=True
    )
    assert import_teams(source(tmp_path), maker, verifier, 4) == 110
    teams = Team.objects.filter(is_demo=False).select_related("user")
    assert teams.count() == 110
    for team in teams:
        assert team.member_count == 4 and team.status == "ACTIVE"
        assert team.user.email.endswith("@example.test")
        assert not team.user.is_staff and team.user.check_password("Synthetic9!Secret")
        assert team.user.password != "Synthetic9!Secret"
    assert Team.objects.get(pk=demo.pk).is_demo
    assert get_user_model().objects.get(pk=maker.pk).is_superuser
    audits = json.dumps(list(AuditEvent.objects.values("before", "after", "reason")))
    assert "Synthetic9!Secret" not in audits


def test_dry_run_saves_no_accounts_or_review_records(staff, tmp_path):
    maker, verifier = staff
    assert (
        import_teams(source(tmp_path, 2), maker, verifier, 4, expected_count=2, dry_run=True) == 2
    )
    assert not Team.objects.exists() and not AuditEvent.objects.exists()
    assert get_user_model().objects.count() == 2


@pytest.mark.parametrize(
    "failure", ["duplicate", "short_password", "email", "staff_conflict", "released"]
)
def test_invalid_roster_rolls_back_entire_batch(staff, tmp_path, failure):
    maker, verifier = staff

    def change(row):
        if failure == "duplicate":
            row[0] = "OFF-000"
        elif failure == "short_password":
            row[3] = "short"
        elif failure == "email":
            row[2] = "invalid-email"
        elif failure == "staff_conflict":
            row[0] = "STAFF"
        return row

    if failure == "staff_conflict":
        get_user_model().objects.create_superuser(username="STAFF")
    elif failure == "released":
        Round.objects.create(number=1, title="Released", state="READY")
    with pytest.raises((CommandError, ApiProblem)):
        import_teams(source(tmp_path, 2, change), maker, verifier, 4, expected_count=2)
    assert not Team.objects.exists() and not AuditEvent.objects.exists()


def test_console_review_gate_and_private_output(staff, tmp_path):
    path = source(tmp_path, 2)
    with pytest.raises(CommandError, match="review-confirmed"):
        call_command("import_team_credentials", csv=str(path), member_count=4, expected_count=2)
    output = StringIO()
    call_command(
        "import_team_credentials",
        csv=str(path),
        member_count=4,
        expected_count=2,
        dry_run=True,
        stdout=output,
    )
    assert "2 real teams" in output.getvalue() and "Synthetic9!Secret" not in output.getvalue()


def test_email_validation_after_review_also_rolls_back_accounts(staff, tmp_path):
    maker, verifier = staff
    existing = get_user_model().objects.create_user(username="existing-linked")
    Team.objects.create(code="OFF-001", name="Existing", user=existing, member_count=4)
    existing.is_staff = True
    existing.save()
    with pytest.raises(CommandError, match="active participant"):
        import_teams(source(tmp_path, 2), maker, verifier, 4, expected_count=2)
    assert (
        Team.objects.count() == 1
        and not get_user_model().objects.filter(username="OFF-000").exists()
    )
    assert not AuditEvent.objects.exists()
