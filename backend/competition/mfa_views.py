import base64
from io import BytesIO

import qrcode
from django.contrib import admin
from django.contrib.auth import get_user_model, login
from django.core.exceptions import ValidationError
from django.db import transaction
from django.http import Http404, HttpResponse
from django.middleware.csrf import rotate_token
from django.shortcuts import redirect, render
from django.utils import timezone
from django.utils.crypto import constant_time_compare
from django.views.decorators.cache import never_cache
from django.views.decorators.debug import sensitive_post_parameters, sensitive_variables
from django.views.decorators.http import require_http_methods, require_safe
from django_otp import verify_token

from .mfa import (
    PENDING_KEY,
    EnrollmentCredentialsForm,
    EnrollmentTokenForm,
    recovery_codes,
    reset_password_attempts,
    start_enrollment,
)
from .models import AuditEvent, StaffMfaEnrollment


def pending_enrollment(request):
    pending = request.session.get(PENDING_KEY, {})
    try:
        age = timezone.now().timestamp() - float(pending["started_at"])
        if not 0 <= age <= 300:
            raise ValueError()
        invite = StaffMfaEnrollment.objects.select_related("user", "issued_by", "device").get(
            pk=pending["invite_id"],
            user_id=pending["user_id"],
            device_id=pending["device_id"],
            used_at__isnull=False,
        )
        user, actor, device = invite.user, invite.issued_by, invite.device
        if not (
            user.is_staff
            and user.is_active
            and actor.is_superuser
            and actor.is_active
            and actor.is_staff
            and device is not None
            and not device.confirmed
            and constant_time_compare(user.get_session_auth_hash(), pending["password_hash"])
        ):
            raise ValueError()
    except (KeyError, TypeError, ValueError, StaffMfaEnrollment.DoesNotExist):
        request.session.pop(PENDING_KEY, None)
        return None
    return invite


@never_cache
@require_http_methods(["GET", "POST"])
@sensitive_post_parameters()
@sensitive_variables()
def enroll(request):
    invite = pending_enrollment(request)
    if invite is not None:
        form = EnrollmentTokenForm(request.POST if request.method == "POST" else None)
        if request.method == "POST" and form.is_valid():
            # Serialize enrollment with resets/parallel browsers; OTP verification commits failures.
            with transaction.atomic():
                user = get_user_model().objects.select_for_update().get(pk=invite.user_id)
                current = pending_enrollment(request)
                device = (
                    verify_token(user, invite.device.persistent_id, form.cleaned_data["token"])
                    if current
                    else None
                )
                if device:
                    device.confirmed = True
                    device.save(update_fields=["confirmed"])
                    codes = recovery_codes(user)
                    request.session.pop(PENDING_KEY, None)
                    user.otp_device = device
                    login(request, user, backend="django.contrib.auth.backends.ModelBackend")
                    reset_password_attempts(user)
                    AuditEvent.objects.create(
                        actor=user,
                        action="staff_mfa_enrolled",
                        after={"user_id": user.pk},
                        reason="Console-authorized staff authenticator confirmed.",
                    )
                    return render(
                        request,
                        "staff_mfa/complete.html",
                        {
                            **admin.site.each_context(request),
                            "title": "MFA enabled",
                            "codes": codes,
                        },
                    )
            form.add_error(
                "token",
                "Code not accepted. Check your phone's automatic time and retry with a new code.",
            )
        return render(
            request,
            "staff_mfa/enroll.html",
            {
                **admin.site.each_context(request),
                "title": "Confirm your authenticator",
                "form": form,
                "setup": True,
                "username": invite.user.username,
                "setup_key": base64.b32encode(invite.device.bin_key).decode().rstrip("="),
            },
        )
    form = EnrollmentCredentialsForm(
        request, data=request.POST if request.method == "POST" else None
    )
    if request.method == "POST" and form.is_valid():
        try:
            pending = start_enrollment(form.get_user(), form.cleaned_data["invitation"])
        except ValidationError as error:
            form.add_error(None, error)
        else:
            request.session.cycle_key()
            rotate_token(request)
            request.session[PENDING_KEY] = pending
            return redirect("staff-mfa-enroll")
    return render(
        request,
        "staff_mfa/enroll.html",
        {
            **admin.site.each_context(request),
            "title": "Enroll staff MFA",
            "form": form,
        },
    )


@never_cache
@require_safe
@sensitive_variables()
def enrollment_qr(request):
    invite = pending_enrollment(request)
    if invite is None:
        raise Http404()
    image = qrcode.make(invite.device.config_url)
    output = BytesIO()
    image.save(output, format="PNG")
    response = HttpResponse(output.getvalue(), content_type="image/png")
    response["X-Content-Type-Options"] = "nosniff"
    return response
