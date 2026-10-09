"""Unsigned placeholders; no qualification, scoring or content approval is fabricated."""

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from competition.buzzer_content import STAGES
from competition.models import AuditEvent, BuzzerQuestion, Round, RoundInformation
from competition.rules import require_staff_permission


class Command(BaseCommand):
    help = "Prepare unverified Round 5 demo placeholders and website-buzzer rules."

    def add_arguments(self, parser):
        parser.add_argument("--actor", default="DEMO-content")

    @transaction.atomic
    def handle(self, *args, **options):
        if not settings.DEBUG:
            raise CommandError("Buzzer demo preparation requires local DEBUG mode.")
        actor = get_user_model().objects.filter(username=options["actor"]).first()
        if actor is None:
            raise CommandError("Content staff account not found.")
        require_staff_permission(actor, "prepare_content")
        round = (
            Round.objects.select_for_update()
            .filter(number=5, is_demo=True)
            .order_by("-attempt_no")
            .first()
        )
        if not round or round.state != "DRAFT":
            raise CommandError(
                "Use an existing demo Round 5 DRAFT; released attempts are preserved."
            )
        if BuzzerQuestion.objects.filter(round=round).exists():
            self.stdout.write("Existing buzzer configuration and questions preserved.")
            return
        round.delivery_mode = "BUZZER"
        round.title = "Buzzer final"
        round.rules_version = "demo-buzzer-v1"
        round.advancement_count = None
        round.active_budget_ms = 300000  # Explicitly synthetic five-minute rehearsal.
        round.rules = {
            **round.rules,
            "demo_only": True,
            "buzzer_order_policy": "database_receipt_time",
            "buzzer_latency_policy": "no_compensation",
            "buzzer_equal_time_policy": "staff_review_required",
            "buzzer_early_policy": "reject_closed_window",
            "ranking_policy": "offline_score_contract_pending",
            "offline_rules_reference": "PENDING — approved offline host rules",
            "delivery_instructions": "Synthetic five-minute demo: website buzzes, offline answers.",
        }
        round.rules.pop("score_schema", None)
        round.approved_by = None
        round.approved_at = None
        round.approval_digest = ""
        round.save()
        for stage in STAGES:
            item = BuzzerQuestion(
                round=round,
                public_id=f"DEMO-STAGE-{stage['number']}-Q1",
                stage=stage["number"],
                version="placeholder-v1",
                source_reference="PLACEHOLDER — private host pack",
                private_content={
                    "answer": "PLACEHOLDER — approved answer pending",
                    "presentation_reference": f"PLACEHOLDER — {stage['title']} host material",
                },
                prepared_by=actor,
            )
            item.full_clean()
            item.save()
        RoundInformation.objects.get_or_create(
            round=round,
            defaults={
                "prepared_by": actor,
                "summary": "Five stages: AI images, keywords, decoding, defects, image guessing.",
                "instructions": (
                    "Buzz on this page. The earliest valid server-recorded press answers offline. "
                    "Phone/network delays receive no compensation."
                ),
                "venue": "PLACEHOLDER — final venue pending",
                "contacts": [],
            },
        )
        AuditEvent.objects.create(
            actor=actor,
            action="prepare_buzzer_demo",
            after={"round_id": round.pk, "rules_version": round.rules_version},
            reason="Unsigned five-stage placeholders; no qualification or scoring fabricated.",
        )
        self.stdout.write(
            "Prepared five unverified questions and unpublished information. "
            "Round 4 qualification and independent review remain required."
        )
