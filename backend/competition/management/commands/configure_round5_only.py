from copy import deepcopy

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from competition.buzzer_scoring_rules import PENALTY_CONTRACT, ROUND5_ONLY_CONTRACT
from competition.models import AuditEvent, Round
from competition.rules import require_staff_permission


class Command(BaseCommand):
    help = "Set a real Round 5 draft to Round-5-only scoring without releasing content or play."

    def add_arguments(self, parser):
        parser.add_argument("--actor", required=True)
        parser.add_argument("--dry-run", action="store_true")
        parser.add_argument("--penalties", action="store_true")

    @transaction.atomic
    def handle(self, *args, **options):
        actor = get_user_model().objects.get(username=options["actor"])
        require_staff_permission(actor, "prepare_content")
        require_staff_permission(actor, "control_round")
        round = (
            Round.objects.select_for_update()
            .filter(number=5, is_demo=False)
            .order_by("-attempt_no")
            .first()
        )
        if round is None or round.state != "DRAFT":
            raise CommandError(
                "Use an existing real Round 5 DRAFT; frozen attempts remain unchanged."
            )
        before = {"rules": deepcopy(round.rules), "rules_version": round.rules_version}
        round.delivery_mode = "BUZZER"
        round.advancement_count = None
        round.rules_version = (
            "event-r5-penalties-20261013-v1"
            if options["penalties"]
            else "event-r5-only-20261013-v1"
        )
        contract = PENALTY_CONTRACT if options["penalties"] else ROUND5_ONLY_CONTRACT
        round.rules = {
            **round.rules,
            "score_schema": deepcopy(contract),
            "ranking_policy": "round5_score_then_last_correct",
        }
        round.rules["buzzer_early_policy"] = (
            "penalize_before_host_go" if options["penalties"] else "reject_closed_window"
        )
        round.approved_by = round.approved_at = None
        round.approval_digest = ""
        round.save()
        AuditEvent.objects.create(
            actor=actor,
            action="configure_round5_only",
            before=before,
            after={"round_id": round.pk, "schema": contract},
            reason=(
                "Organizer decision: winner uses only Round 5 points; no earlier score carry-over."
            ),
        )
        self.stdout.write(
            f"R5 {round.pk}: 30 possible marks, no carry-over, one winner. "
            "Still DRAFT; content and independent approval required."
        )
        if options["penalties"]:
            self.stdout.write(
                "Wrong: -1 in every stage. Early: -1 once per team/question. "
                "Host GO required; no passing."
            )
        if options["dry_run"]:
            transaction.set_rollback(True)
            self.stdout.write("Dry run rolled back.")
