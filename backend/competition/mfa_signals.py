from django.utils import timezone

from .mfa import VERIFIED_KEY
from .models import AuditEvent


def record_staff_verification(sender, request, user, **kwargs):
    device = getattr(user, "otp_device", None)
    if user.is_staff and device is not None and device.confirmed and device.user_id == user.pk:
        request.session[VERIFIED_KEY] = timezone.now().timestamp()
        AuditEvent.objects.create(
            actor=user,
            action="staff_mfa_login",
            after={"user_id": user.pk, "factor": device._meta.model_name},
            reason="Staff password and one-time code verified.",
        )
    else:
        request.session.pop(VERIFIED_KEY, None)
