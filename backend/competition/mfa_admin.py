from django.conf import settings
from django.contrib.admin.sites import AdminSite
from django_otp.admin import OTPAdminSite

from .mfa import StaffMfaAuthenticationForm, staff_mfa_verified


class StaffAdminSite(OTPAdminSite):
    login_form = StaffMfaAuthenticationForm
    login_template = "staff_mfa/login.html"

    def __init__(self, name="admin"):
        super().__init__(name=name)

    def has_permission(self, request):
        if not settings.STAFF_MFA_REQUIRED:
            return AdminSite.has_permission(self, request)
        return AdminSite.has_permission(self, request) and staff_mfa_verified(request)
