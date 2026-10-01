from django.contrib import admin

from . import models


class ReadOnlyAdmin(admin.ModelAdmin):
    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(models.Round)
class RoundAdmin(ReadOnlyAdmin):
    list_display = ("number", "attempt_no", "title", "state", "is_demo", "rules_version")
    list_filter = ("state", "is_demo")


@admin.register(models.Team)
class TeamAdmin(ReadOnlyAdmin):
    list_display = ("code", "name", "status", "member_count", "is_demo")
    search_fields = ("code", "name")


@admin.register(models.Mission)
class MissionAdmin(ReadOnlyAdmin):
    list_display = ("public_id", "round", "is_practice", "available", "verified_at")
    exclude = ("answer_verifiers", "token", "fallback_code", "keyword")
    list_filter = ("round", "is_practice")


for model in (
    models.RoundPhase,
    models.TeamSession,
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
