import pytest


@pytest.fixture(autouse=True)
def isolate_existing_gameplay_tests_from_staff_authentication(settings, request, monkeypatch):
    # Legacy suites test authorization/scoring with force_login. MFA has a separate
    # suite with the real login flow; production is always enforced independently.
    settings.STAFF_MFA_REQUIRED = request.node.get_closest_marker("staff_mfa") is not None
    if not settings.STAFF_MFA_REQUIRED:
        from django.contrib import admin
        from django.contrib.admin.forms import AdminAuthenticationForm

        monkeypatch.setattr(admin.site, "login_form", AdminAuthenticationForm)
        monkeypatch.setattr(admin.site, "login_template", "admin/login.html")
