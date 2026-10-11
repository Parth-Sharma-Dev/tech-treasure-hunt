"""Staff-only MFA lifecycle; passwords alone never grant staff HTTP access."""

import hashlib
import secrets
from datetime import timedelta

from django import forms
from django.conf import settings
from django.contrib.admin.forms import AdminAuthenticationForm
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone
from django.utils.crypto import constant_time_compare
from django_otp.admin import OTPAdminAuthenticationForm
from django_otp.plugins.otp_static.models import StaticDevice, StaticToken
from django_otp.plugins.otp_totp.models import TOTPDevice

from .models import AuditEvent, StaffLoginWindow, StaffMfaEnrollment

PENDING_KEY = "staff_mfa_enrollment"
VERIFIED_KEY = "staff_mfa_verified_at"


def staff_mfa_verified(request):
    user = request.user
    if not (user.is_authenticated and user.is_active and user.is_staff):
        return False
    if not settings.STAFF_MFA_REQUIRED:
        return True
    device = getattr(user, "otp_device", None)
    if device is None or not device.confirmed or device.user_id != user.pk:
        return False
    try:
        age = timezone.now().timestamp() - float(request.session[VERIFIED_KEY])
    except (KeyError, TypeError, ValueError, OverflowError):
        return False
    return 0 <= age <= settings.STAFF_MFA_MAX_AGE_SECONDS


@transaction.atomic
def password_attempt(username):
    user = (
        get_user_model()
        .objects.select_for_update()
        .filter(username=username, is_staff=True)
        .first()
    )
    if user is None:
        return
    now = timezone.now()
    window, _ = StaffLoginWindow.objects.get_or_create(user=user, defaults={"started_at": now})
    if now - window.started_at >= timedelta(minutes=5):
        window.started_at, window.attempts = now, 0
    if window.attempts >= 5:
        raise ValidationError("Too many staff sign-in attempts. Wait five minutes and try again.")
    window.attempts += 1
    window.save()


def reset_password_attempts(user):
    StaffLoginWindow.objects.filter(user=user).update(attempts=0, started_at=timezone.now())


class StaffMfaAuthenticationForm(OTPAdminAuthenticationForm):
    factor = forms.ChoiceField(
        label="Second factor",
        choices=[("totp", "Authenticator app"), ("recovery", "One-time recovery code")],
    )
    otp_token = forms.CharField(
        label="Authentication code",
        max_length=16,
        widget=forms.TextInput(attrs={"autocomplete": "one-time-code"}),
    )

    def clean(self):
        password_attempt(self.cleaned_data.get("username", ""))
        cleaned = AdminAuthenticationForm.clean(self)
        user = self.get_user()
        if user is not None:
            model = StaticDevice if cleaned.get("factor") == "recovery" else TOTPDevice
            device = model.objects.filter(user=user, confirmed=True).order_by("pk").first()
            cleaned["otp_device"] = device.persistent_id if device else ""
            self.cleaned_data = cleaned
            try:
                self.clean_otp(user)
            finally:
                # django-otp normally re-renders the password on OTP errors; keep it private.
                self.fields["password"].widget.render_value = False
            reset_password_attempts(user)
        return cleaned


class EnrollmentCredentialsForm(AdminAuthenticationForm):
    invitation = forms.CharField(
        label="Enrollment code",
        max_length=128,
        widget=forms.PasswordInput(render_value=False, attrs={"autocomplete": "off"}),
    )

    def clean(self):
        password_attempt(self.cleaned_data.get("username", ""))
        return super().clean()


class EnrollmentTokenForm(forms.Form):
    token = forms.RegexField(
        r"\A[0-9]{6}\Z",
        label="Six-digit authenticator code",
        widget=forms.TextInput(attrs={"autocomplete": "one-time-code", "inputmode": "numeric"}),
    )


@transaction.atomic
def issue_enrollment(user, actor, reason):
    if not (actor.is_active and actor.is_staff and actor.is_superuser):
        raise ValidationError("An active superuser must authorize staff enrollment.")
    user = get_user_model().objects.select_for_update().get(pk=user.pk)
    if not user.is_active or not user.is_staff:
        raise ValidationError("Enrollment requires an active staff account.")
    if TOTPDevice.objects.filter(user=user, confirmed=True).exists():
        raise ValidationError(
            "This account already has MFA. Use reviewed reset if its device is lost."
        )
    if not reason.strip() or len(reason) > 500:
        raise ValidationError("Supply an enrollment reason of up to 500 characters.")
    now = timezone.now()
    StaffMfaEnrollment.objects.filter(user=user, used_at__isnull=True).update(expires_at=now)
    code = secrets.token_urlsafe(32)
    invite = StaffMfaEnrollment.objects.create(
        user=user,
        issued_by=actor,
        code_hash=hashlib.sha256(code.encode()).hexdigest(),
        issued_at=now,
        expires_at=now + timedelta(minutes=30),
        reason=reason,
    )
    AuditEvent.objects.create(
        actor=actor,
        action="staff_mfa_enrollment_issued",
        reason=reason,
        after={"user_id": user.pk, "enrollment_id": invite.pk},
    )
    return code


@transaction.atomic
def start_enrollment(user, code):
    password_hash = user.get_session_auth_hash()
    user = get_user_model().objects.select_for_update().get(pk=user.pk)
    if not (
        user.is_active
        and user.is_staff
        and constant_time_compare(password_hash, user.get_session_auth_hash())
    ):
        raise ValidationError("Staff credentials changed. Start enrollment again.")
    invite = (
        StaffMfaEnrollment.objects.select_for_update()
        .filter(
            user=user,
            code_hash=hashlib.sha256(code.encode()).hexdigest(),
            used_at__isnull=True,
            expires_at__gt=timezone.now(),
            issued_by__is_active=True,
            issued_by__is_staff=True,
            issued_by__is_superuser=True,
        )
        .first()
    )
    if invite is None or TOTPDevice.objects.filter(user=user, confirmed=True).exists():
        raise ValidationError("Enrollment is unavailable. Ask the organizer for a fresh code.")
    TOTPDevice.objects.filter(user=user, confirmed=False).delete()
    device = TOTPDevice.objects.create(
        user=user, name="Authenticator", confirmed=False, tolerance=1
    )
    invite.used_at, invite.device = timezone.now(), device
    invite.save(update_fields=["used_at", "device"])
    return {
        "user_id": user.pk,
        "invite_id": invite.pk,
        "device_id": device.pk,
        "password_hash": user.get_session_auth_hash(),
        "started_at": timezone.now().timestamp(),
    }


def recovery_codes(user):
    # Caller holds the user lock and has authenticated a fresh enrollment or password.
    StaticDevice.objects.filter(user=user).delete()
    device = StaticDevice.objects.create(user=user, name="Recovery codes", confirmed=True)
    codes = set()
    while len(codes) < 10:
        codes.add(secrets.token_hex(8))
    StaticToken.objects.bulk_create([StaticToken(device=device, token=code) for code in codes])
    return sorted(codes)


@transaction.atomic
def reset_staff_mfa(user, actor, reason):
    if not (actor.is_active and actor.is_staff and actor.is_superuser) or actor.pk == user.pk:
        raise ValidationError("A different active superuser must authorize a lost-device reset.")
    if not reason.strip() or len(reason) > 500:
        raise ValidationError(
            "Record the verified identity and reset reason (up to 500 characters)."
        )
    user = get_user_model().objects.select_for_update().get(pk=user.pk)
    if not user.is_active or not user.is_staff:
        raise ValidationError("Only an active staff account can receive a reset.")
    TOTPDevice.objects.filter(user=user).delete()
    StaticDevice.objects.filter(user=user).delete()
    StaffMfaEnrollment.objects.filter(user=user).update(expires_at=timezone.now())
    reset_password_attempts(user)
    AuditEvent.objects.create(
        actor=actor,
        action="staff_mfa_reset",
        after={"user_id": user.pk},
        reason=reason,
    )
    return issue_enrollment(user, actor, reason)


def invalidate_restored_authentication(alias):
    """Revoke restored cookies, enrollment invites and potentially spent backup codes."""
    from django.contrib.sessions.models import Session
    from django.db import connections

    tables = set(connections[alias].introspection.table_names())
    for model in (Session, StaticToken):
        if model._meta.db_table in tables:
            model.objects.using(alias).all().delete()
    if StaffMfaEnrollment._meta.db_table in tables:
        StaffMfaEnrollment.objects.using(alias).update(expires_at=timezone.now())
