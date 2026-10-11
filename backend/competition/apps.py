from django.apps import AppConfig


class CompetitionConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "competition"

    def ready(self):
        from django.contrib.auth.signals import user_logged_in

        from .mfa_signals import record_staff_verification

        user_logged_in.connect(record_staff_verification, dispatch_uid="tth.staff_mfa_login")
