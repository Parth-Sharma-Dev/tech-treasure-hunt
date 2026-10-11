import hashlib
from datetime import timedelta
from io import StringIO

import pytest
from django.contrib import admin
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.test import Client
from django.utils import timezone
from django_otp import DEVICE_ID_SESSION_KEY
from django_otp.oath import totp
from django_otp.plugins.otp_static.models import StaticDevice, StaticToken
from django_otp.plugins.otp_totp.models import TOTPDevice
from test_gameplay import game as _game
from test_gameplay import open_mission

from competition.mfa import PENDING_KEY, VERIFIED_KEY, issue_enrollment
from competition.models import AuditEvent, StaffLoginWindow, StaffMfaEnrollment

pytestmark = [pytest.mark.django_db, pytest.mark.staff_mfa]
game = _game
PASSWORD = "synthetic-staff-test-password"


@pytest.fixture
def staff(settings):
    settings.PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]
    return get_user_model().objects.create_superuser(username="mfa-staff", password=PASSWORD)


def code(device):
    return f"{totp(device.bin_key):06d}"


def post(client, path, data):
    csrf = client.get("/api/auth/csrf").json()["csrf_token"]
    return client.post(path, data, HTTP_X_CSRFTOKEN=csrf)


def sign_in(client, staff, otp, factor="totp", **extra):
    return post(
        client,
        "/admin/login/",
        {
            "username": staff.username,
            "password": PASSWORD,
            "otp_token": otp,
            "factor": factor,
            "next": "/admin/",
            **extra,
        },
    )


def verified_client(staff):
    device = TOTPDevice.objects.create(user=staff, confirmed=True, name="Authenticator")
    client = Client(enforce_csrf_checks=True)
    assert sign_in(client, staff, code(device)).status_code == 302
    return client, device


@pytest.mark.parametrize(
    "path",
    [
        "/api/staff/rounds",
        "/api/staff/results",
        "/api/staff/roster",
        "/api/staff/buzzer/rounds",
        "/api/staff/coding/rounds",
        "/api/staff/missions/1/image",
        "/api/staff/rounds/1/publish",
        "/api/staff/rounds/1/buzzer/control",
        "/api/staff/rounds/1/imports/wayground",
        "/api/staff/rounds/1/exports/checkpoint",
        "/api/staff/teams/1/credentials",
    ],
)
def test_password_only_session_cannot_read_or_write_any_staff_workflow(staff, path):
    client = Client(enforce_csrf_checks=True)
    client.force_login(staff)
    for response in [
        client.get(path),
        client.post(path, data="invalid-body", content_type="text/plain"),
    ]:
        assert response.status_code == 403
        assert response.json()["error"]["code"] == "staff_mfa_required"
        assert response["Cache-Control"] == "no-store"
    assert client.get("/admin/").status_code == 302


def test_password_without_second_factor_never_logs_staff_in(staff):
    client = Client(enforce_csrf_checks=True)
    response = sign_in(client, staff, "")
    assert response.status_code == 200
    assert "_auth_user_id" not in client.session
    assert PASSWORD not in response.content.decode()


def test_valid_authenticator_unlocks_admin_and_api_and_keeps_csrf_required(staff):
    client, device = verified_client(staff)
    assert client.session[DEVICE_ID_SESSION_KEY] == device.persistent_id
    assert VERIFIED_KEY in client.session
    assert client.get("/admin/").status_code == 200
    assert client.get("/api/staff/rounds").status_code == 200
    assert (
        client.post("/api/staff/roster/change", {}, content_type="application/json").status_code
        == 403
    )
    assert AuditEvent.objects.filter(action="staff_mfa_login").count() == 1


def test_totp_is_bound_to_staff_identity_and_cannot_be_replayed(staff):
    device = TOTPDevice.objects.create(user=staff, confirmed=True)
    other = get_user_model().objects.create_superuser(username="mfa-other", password=PASSWORD)
    other_device = TOTPDevice.objects.create(user=other, confirmed=True)
    first = Client()
    token = code(device)
    assert sign_in(first, staff, token).status_code == 302
    assert sign_in(Client(), staff, token).status_code == 200
    # Supplying another account's device ID cannot change the selected own factor.
    assert (
        sign_in(
            Client(), staff, code(other_device), otp_device=other_device.persistent_id
        ).status_code
        == 200
    )


def test_recovery_code_requires_password_and_is_consumed_once(staff):
    TOTPDevice.objects.create(user=staff, confirmed=True)
    recovery = StaticDevice.objects.create(user=staff, confirmed=True)
    token = StaticToken.objects.create(device=recovery, token="0123456789abcdef")
    assert (
        sign_in(Client(), staff, token.token, factor="recovery", password="wrong").status_code
        == 200
    )
    assert StaticToken.objects.filter(pk=token.pk).exists()
    assert sign_in(Client(), staff, token.token, factor="recovery").status_code == 302
    assert not StaticToken.objects.filter(pk=token.pk).exists()
    assert sign_in(Client(), staff, token.token, factor="recovery").status_code == 200


def test_expired_deleted_or_unconfirmed_device_session_is_blocked(staff):
    client, device = verified_client(staff)
    session = client.session
    session[VERIFIED_KEY] = (timezone.now() - timedelta(hours=13)).timestamp()
    session.save()
    assert client.get("/api/staff/rounds").status_code == 403
    session = client.session
    session[VERIFIED_KEY] = timezone.now().timestamp()
    session.save()
    device.confirmed = False
    device.save()
    assert client.get("/api/staff/rounds").status_code == 403
    device.delete()
    assert client.get("/api/staff/rounds").status_code == 403


def test_plain_password_session_cannot_forge_mfa_using_timestamp_only(staff):
    client = Client()
    client.force_login(staff)
    session = client.session
    session[VERIFIED_KEY] = timezone.now().timestamp()
    session.save()
    assert client.get("/api/staff/rounds").status_code == 403


def test_staff_password_attempts_are_persistently_bounded(staff):
    for _ in range(5):
        assert sign_in(Client(), staff, "", password="wrong").status_code == 200
    response = sign_in(Client(), staff, "", password=PASSWORD)
    assert "Too many staff sign-in attempts" in response.content.decode()
    assert StaffLoginWindow.objects.get(user=staff).attempts == 5
    StaffLoginWindow.objects.filter(user=staff).update(
        started_at=timezone.now() - timedelta(minutes=6)
    )
    assert "Too many staff sign-in attempts" not in sign_in(Client(), staff, "").content.decode()


def test_enrollment_requires_console_code_and_never_stores_it_in_audit(staff):
    invite = issue_enrollment(staff, staff, "Supervised first setup")
    row = StaffMfaEnrollment.objects.get(user=staff)
    assert row.code_hash == hashlib.sha256(invite.encode()).hexdigest()
    assert invite not in str(list(AuditEvent.objects.values()))
    client = Client(enforce_csrf_checks=True)
    response = post(
        client,
        "/staff-mfa/enroll/",
        {
            "username": staff.username,
            "password": PASSWORD,
            "invitation": "wrong",
        },
    )
    assert response.status_code == 200
    assert "_auth_user_id" not in client.session
    assert client.get("/staff-mfa/qr/").status_code == 404
    response = post(
        client,
        "/staff-mfa/enroll/",
        {
            "username": staff.username,
            "password": PASSWORD,
            "invitation": invite,
        },
    )
    assert response.status_code == 302
    assert "_auth_user_id" not in client.session
    assert client.get("/api/staff/rounds").status_code == 403
    qr = client.get("/staff-mfa/qr/")
    assert qr.status_code == 200 and qr["Content-Type"] == "image/png"
    assert "no-store" in qr["Cache-Control"]
    device = TOTPDevice.objects.get(pk=client.session[PENDING_KEY]["device_id"])
    response = post(client, "/staff-mfa/enroll/", {"token": code(device)})
    assert response.status_code == 200 and b"MFA enabled" in response.content
    device.refresh_from_db()
    row.refresh_from_db()
    assert device.confirmed and row.used_at
    assert PENDING_KEY not in client.session
    assert client.get("/admin/").status_code == 200
    assert StaticToken.objects.filter(device__user=staff).count() == 10
    assert client.get("/staff-mfa/qr/").status_code == 404
    assert b"Save these ten" not in client.get("/staff-mfa/enroll/").content


def test_enrollment_code_expiry_replay_and_staff_account_restrictions(staff):
    invite = issue_enrollment(staff, staff, "Initial setup")
    StaffMfaEnrollment.objects.filter(user=staff).update(
        expires_at=timezone.now() - timedelta(seconds=1)
    )
    client = Client()
    data = {"username": staff.username, "password": PASSWORD, "invitation": invite}
    assert post(client, "/staff-mfa/enroll/", data).status_code == 200
    assert not TOTPDevice.objects.filter(user=staff).exists()
    data["invitation"] = issue_enrollment(staff, staff, "Reissued setup")
    assert post(client, "/staff-mfa/enroll/", data).status_code == 302
    assert post(Client(), "/staff-mfa/enroll/", data).status_code == 200
    with pytest.raises(ValidationError):
        user = get_user_model().objects.create_user(username="not-staff")
        issue_enrollment(user, staff, "Not allowed")


def test_setup_expires_and_password_change_invalidates_pending_qr(staff):
    client = Client()
    invite = issue_enrollment(staff, staff, "Initial setup")
    post(
        client,
        "/staff-mfa/enroll/",
        {"username": staff.username, "password": PASSWORD, "invitation": invite},
    )
    staff.set_password("new-test-only-password")
    staff.save()
    assert client.get("/staff-mfa/qr/").status_code == 404


def test_admin_login_and_enrollment_enforce_csrf(staff):
    client = Client(enforce_csrf_checks=True)
    assert (
        client.post("/admin/login/", {"username": staff.username, "password": PASSWORD}).status_code
        == 403
    )
    assert (
        client.post(
            "/staff-mfa/enroll/", {"username": staff.username, "password": PASSWORD}
        ).status_code
        == 403
    )


def test_team_login_and_mission_open_are_unchanged(game):
    _, missions, _, _, client = game
    assert client.get("/api/me").status_code == 200
    assert open_mission(client, missions[0])["opened"] is True
    assert client.get("/api/staff/rounds").status_code == 403


def test_otp_secrets_are_not_registered_in_admin(staff):
    assert not admin.site.is_registered(TOTPDevice)
    assert not admin.site.is_registered(StaticDevice)
    client, _ = verified_client(staff)
    assert client.get("/admin/otp_totp/totpdevice/").status_code == 404
    assert client.get("/admin/otp_static/staticdevice/").status_code == 404


def test_console_command_requires_authorized_actor(staff):
    output = StringIO()
    call_command(
        "issue_staff_mfa_enrollment",
        username=staff.username,
        actor=staff.username,
        reason="Supervised setup",
        stdout=output,
    )
    assert "30 minutes" in output.getvalue()
    assert StaffMfaEnrollment.objects.filter(user=staff).count() == 1


def test_enrollment_qr_expires_after_five_minutes(staff):
    client = Client()
    invitation = issue_enrollment(staff, staff, "Initial setup")
    post(
        client,
        "/staff-mfa/enroll/",
        {
            "username": staff.username,
            "password": PASSWORD,
            "invitation": invitation,
        },
    )
    session = client.session
    pending = session[PENDING_KEY]
    pending["started_at"] = (timezone.now() - timedelta(minutes=6)).timestamp()
    session[PENDING_KEY] = pending
    session.save()
    assert client.get("/staff-mfa/qr/").status_code == 404
    assert not TOTPDevice.objects.filter(user=staff, confirmed=True).exists()


def test_verified_staff_still_needs_endpoint_permissions(staff):
    staff.is_superuser = False
    staff.save()
    client, _ = verified_client(staff)
    assert client.get("/api/staff/rounds").status_code == 403


def test_admin_sign_in_rejects_external_return_url(staff):
    device = TOTPDevice.objects.create(user=staff, confirmed=True)
    response = sign_in(Client(), staff, code(device), next="https://untrusted.example/")
    assert response.status_code == 302
    assert "untrusted.example" not in response["Location"]


def test_verified_session_is_invalidated_when_staff_account_is_deactivated(staff):
    client, _ = verified_client(staff)
    staff.is_active = False
    staff.save()
    assert client.get("/api/staff/rounds").status_code == 403


def test_failed_otp_does_not_reflect_password_or_invite_in_html(staff):
    TOTPDevice.objects.create(user=staff, confirmed=True)
    response = sign_in(Client(), staff, "invalid")
    assert response.status_code == 200
    assert PASSWORD not in response.content.decode()
