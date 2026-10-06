import uuid

from django import forms
from django.contrib import admin, messages
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.utils import timezone

from . import models
from .answers import answer_digest
from .rules import approve_rules, mark_ready
from .sessions import revoke_session


def permitted(request, codename):
    return (
        request.user.is_active
        and request.user.is_staff
        and request.user.has_perm(f"competition.{codename}")
    )


class ReadOnlyAdmin(admin.ModelAdmin):
    view_permissions = ("adjudicate", "verify_evidence")

    def has_view_permission(self, request, obj=None):
        return super().has_view_permission(request, obj) or any(
            permitted(request, permission) for permission in self.view_permissions
        )

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(models.Round)
class RoundAdmin(ReadOnlyAdmin):
    view_permissions = ("prepare_content", "control_round", "verify_evidence", "publish_results")
    list_display = ("number", "attempt_no", "title", "state", "is_demo", "rules_version")
    list_filter = ("state", "is_demo")
    readonly_fields = (
        "attempt_id",
        "state",
        "play_mode",
        "rules_snapshot",
        "rules_digest",
        "approval_digest",
        "approved_by",
        "approved_at",
        "accumulated_active_ms",
        "live_started_at",
        "phase_started_at",
        "deadline_at",
        "control_version",
    )
    actions = ("approve_selected_rules", "ready_selected_rounds")

    def get_actions(self, request):
        actions = super().get_actions(request)
        if not permitted(request, "verify_evidence"):
            actions.pop("approve_selected_rules", None)
        if not permitted(request, "control_round"):
            actions.pop("ready_selected_rounds", None)
        return actions

    def has_add_permission(self, request):
        return permitted(request, "prepare_content")

    def has_change_permission(self, request, obj=None):
        return permitted(request, "prepare_content") and (
            obj is None or obj.state == models.Round.State.DRAFT
        )

    @admin.action(permissions=["view"], description="Approve the current draft rule settings")
    def approve_selected_rules(self, request, queryset):
        for round in queryset:
            try:
                approve_rules(round.pk, request.user)
            except ValidationError as error:
                self.message_user(request, f"{round}: {'; '.join(error.messages)}", messages.ERROR)
            else:
                self.message_user(request, f"{round}: current settings approved.", messages.SUCCESS)

    @admin.action(permissions=["view"], description="Validate and mark approved rounds READY")
    def ready_selected_rounds(self, request, queryset):
        for round in queryset:
            try:
                mark_ready(round.pk, request.user)
            except ValidationError as error:
                self.message_user(request, f"{round}: {'; '.join(error.messages)}", messages.ERROR)
            else:
                self.message_user(request, f"{round}: READY.", messages.SUCCESS)


@admin.register(models.Team)
class TeamAdmin(ReadOnlyAdmin):
    view_permissions = ("prepare_content", "control_round", "verify_evidence")
    list_display = ("code", "name", "status", "member_count", "is_demo")
    search_fields = ("code", "name")


class MissionForm(forms.ModelForm):
    answer = forms.RegexField(
        regex=r"\A[0-9]{4}\Z",
        required=False,
        strip=False,
        widget=forms.PasswordInput(render_value=False),
        help_text="Four ASCII digits. Leave blank to preserve an existing answer verifier.",
    )

    class Meta:
        model = models.Mission
        exclude = ("answer_verifiers",)

    def clean(self):
        cleaned = super().clean()
        if not self.instance.pk and not cleaned.get("answer"):
            self.add_error("answer", "A new mission needs a four-digit answer.")
        return cleaned


@admin.register(models.Mission)
class MissionAdmin(ReadOnlyAdmin):
    view_permissions = ("prepare_content", "verify_evidence")
    form = MissionForm
    list_display = ("public_id", "round", "is_practice", "available", "verified_at")
    exclude = ("answer_verifiers",)
    readonly_fields = (
        "token",
        "fallback_code",
        "prepared_by",
        "verified_by",
        "verified_at",
        "is_void",
    )
    list_filter = ("round", "is_practice")
    actions = ("verify_selected_missions",)

    def get_fields(self, request, obj=None):
        fields = super().get_fields(request, obj)
        if obj is not None and not self.has_change_permission(request, obj):
            return [field for field in fields if field != "answer"]
        return fields

    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        if db_field.name == "round":
            kwargs["queryset"] = models.Round.objects.filter(state=models.Round.State.DRAFT)
        return super().formfield_for_foreignkey(db_field, request, **kwargs)

    def get_actions(self, request):
        actions = super().get_actions(request)
        if not permitted(request, "verify_evidence"):
            actions.pop("verify_selected_missions", None)
        return actions

    def has_add_permission(self, request):
        return permitted(request, "prepare_content")

    def has_change_permission(self, request, obj=None):
        return permitted(request, "prepare_content") and (
            obj is None or obj.round.state == models.Round.State.DRAFT
        )

    @transaction.atomic
    def save_model(self, request, obj, form, change):
        obj.prepared_by = request.user
        obj.verified_by = None
        obj.verified_at = None
        obj.save()
        if answer := form.cleaned_data.get("answer"):
            version = f"draft-{timezone.now().isoformat()}"
            obj.answer_verifiers = [
                {"version": version, "digest": answer_digest(obj.pk, version, answer)}
            ]
            obj.save(update_fields=["answer_verifiers"])

    @admin.action(
        permissions=["view"], description="Attest to independent end-to-end mission verification"
    )
    def verify_selected_missions(self, request, queryset):
        if not permitted(request, "verify_evidence"):
            raise PermissionDenied("Independent verification permission is required.")
        for selected in queryset:
            with transaction.atomic():
                round = models.Round.objects.select_for_update().get(pk=selected.round_id)
                mission = models.Mission.objects.select_for_update().get(pk=selected.pk)
                if (
                    round.state != models.Round.State.DRAFT
                    or mission.prepared_by_id is None
                    or mission.prepared_by_id == request.user.pk
                ):
                    self.message_user(
                        request,
                        f"{mission}: requires a draft and an independent verifier.",
                        messages.ERROR,
                    )
                    continue
                mission.verified_by = request.user
                mission.verified_at = timezone.now()
                mission.save(update_fields=["verified_by", "verified_at"])
                models.AuditEvent.objects.create(
                    actor=request.user,
                    action="verify_mission",
                    after={"mission_id": mission.pk},
                    reason="Staff attests to independently checking the mission end to end.",
                )
                self.message_user(request, f"{mission}: verification recorded.", messages.SUCCESS)


@admin.register(models.TeamSession)
class TeamSessionAdmin(ReadOnlyAdmin):
    view_permissions = ("control_round",)
    exclude = ("session_key",)
    list_display = ("id", "team", "created_at", "last_seen_at", "expires_at", "revoked_at")
    list_filter = ("team",)
    actions = ("revoke_stale_sessions",)

    def get_actions(self, request):
        actions = super().get_actions(request)
        if not permitted(request, "control_round"):
            actions.pop("revoke_stale_sessions", None)
        return actions

    @admin.action(permissions=["view"], description="Revoke selected stale browser sessions")
    def revoke_stale_sessions(self, request, queryset):
        for record in queryset:
            revoke_session(
                record.team_id,
                record.pk,
                request.user,
                str(uuid.uuid4()),
                "Staff-assisted stale browser removal from Django admin.",
            )
        self.message_user(request, "Selected browser sessions were revoked.", messages.SUCCESS)


for model in (
    models.RoundPhase,
    models.Visit,
    models.AttemptState,
    models.SubmissionDecision,
    models.Completion,
    models.Incident,
    models.MissionResolution,
    models.ImportBatch,
    models.ScoreRevision,
    models.ResultSnapshot,
    models.PaperWindow,
    models.AuditEvent,
):
    admin.site.register(model, ReadOnlyAdmin)
