"""Apply the supplied scoring contract to unsigned demo drafts only."""

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from competition.buzzer_scoring_rules import CONTRACT
from competition.models import AuditEvent, BuzzerQuestion, Round
from competition.rules import require_staff_permission


class Command(BaseCommand):
    help = "Prepare 25 unverified demo question slots and the current 30-mark final contract."

    def add_arguments(self, parser):
        parser.add_argument("--actor", default="DEMO-content")

    @transaction.atomic
    def handle(self, *args, **options):
        if not settings.DEBUG:
            raise CommandError("Scoring demo preparation requires DEBUG.")
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
        if not round or round.state != "DRAFT" or round.delivery_mode != "BUZZER":
            raise CommandError(
                "Use an existing BUZZER demo Round 5 DRAFT; released attempts are preserved."
            )
        counts = [
            BuzzerQuestion.objects.filter(round=round, stage=stage).count() for stage in range(1, 6)
        ]
        if any(count > 5 for count in counts):
            raise CommandError("Review the draft question set; each stage requires five questions.")
        created = []
        for stage, count in enumerate(counts, 1):
            slot = 1
            while count < 5:
                public_id = f"DEMO-STAGE-{stage}-Q{slot}"
                slot += 1
                if BuzzerQuestion.objects.filter(round=round, public_id=public_id).exists():
                    continue
                question = BuzzerQuestion.objects.create(
                    round=round,
                    stage=stage,
                    public_id=public_id,
                    version="placeholder-v1",
                    source_reference="PLACEHOLDER — approved host pack",
                    private_content={
                        "answer": "PLACEHOLDER — approved answer",
                        "presentation_reference": "PLACEHOLDER — private material",
                    },
                    prepared_by=actor,
                )
                created.append(question.pk)
                count += 1
        changed = (
            created
            or round.rules.get("score_schema") != CONTRACT
            or round.rules.get("ranking_policy") != "cumulative_score_then_last_correct"
        )
        if changed:
            round.rules = {
                **round.rules,
                "score_schema": dict(CONTRACT),
                "ranking_policy": "cumulative_score_then_last_correct",
            }
            if round.rules.get("qualification_tie_policy") not in [
                "block_exact_ties",
                "supervised_reserve_question",
            ]:
                round.rules["qualification_tie_policy"] = "block_exact_ties"
            round.approved_by, round.approved_at, round.approval_digest = None, None, ""
            round.save()
            AuditEvent.objects.create(
                actor=actor,
                action="prepare_buzzer_scoring_demo",
                after={
                    "round_id": round.pk,
                    "created_question_ids": created,
                    "score_schema": CONTRACT,
                },
                reason="Organizer scoring; no content approval or final results fabricated.",
            )
        self.stdout.write(
            f"Prepared {len(created)} placeholders; 25-question/30-mark contract configured. "
            "Current contract: 30 marks; stage 5 word encoding earns 2/question. "
            "Actual content and prior final results remain required."
        )
