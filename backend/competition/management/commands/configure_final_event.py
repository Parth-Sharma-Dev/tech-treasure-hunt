from copy import deepcopy

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from competition.final_event_settings import ROUND1_RULES, ROUND2_RULES
from competition.models import AuditEvent, Round
from competition.rules import readiness_errors, require_staff_permission


class Command(BaseCommand):
    help = "Apply the approved R1/R2 draft settings using production staff IDs."

    def add_arguments(self, parser):
        parser.add_argument("--actor", default="parth")
        parser.add_argument("--verifier", default="verifier")
        parser.add_argument("--dry-run", action="store_true")

    @transaction.atomic
    def handle(self, *args, **options):
        users = get_user_model()
        try:
            actor = users.objects.get(username=options["actor"])
            verifier = users.objects.get(username=options["verifier"])
            require_staff_permission(actor, "prepare_content")
            require_staff_permission(actor, "control_round")
            require_staff_permission(verifier, "verify_evidence")
            require_staff_permission(verifier, "publish_results")
        except users.DoesNotExist:
            raise CommandError("Create/check the named production staff accounts first.") from None
        if actor.pk == verifier.pk:
            raise CommandError("Use a different independent verifier.")
        owners = {
            name: actor.pk
            for name in ("technical_lead", "content_lead", "operations_lead", "adjudicator")
        }
        owners["verifier"] = verifier.pk
        targets = []
        for number in (1, 2):
            round = (
                Round.objects.select_for_update()
                .filter(number=number, is_demo=False)
                .order_by("-attempt_no")
                .first()
            )
            if not round or round.state != "DRAFT":
                raise CommandError(
                    f"Round {number} must exist as a real DRAFT; released rules stay frozen."
                )
            targets.append(round)
        for round, rules, cut in zip(targets, (ROUND1_RULES, ROUND2_RULES), (50, 20), strict=True):
            before = {
                "rules": round.rules,
                "owners": round.owners,
                "budget_ms": round.active_budget_ms,
                "cut": round.advancement_count,
            }
            round.rules = deepcopy(rules)
            round.rules_version = f"event-r{round.number}-20261012-v1"
            round.owners = owners
            round.active_budget_ms = 3600000
            round.advancement_count = cut
            round.approved_by = None
            round.approved_at = None
            round.approval_digest = ""
            round.save()
            AuditEvent.objects.create(
                actor=actor,
                action="configure_final_event_rules",
                before=before,
                after={
                    "round_id": round.pk,
                    "rules_version": round.rules_version,
                    "budget_ms": round.active_budget_ms,
                    "cut": cut,
                },
                reason="Organizer approved 60-minute R1/R2, 50/20 qualifiers and 5-minute appeals.",
            )
            self.stdout.write(
                f"Round {round.number} ID {round.pk}: settings prepared; not released."
            )
            for error in readiness_errors(round):
                self.stdout.write(f"  Remaining: {error}")
        if options["dry_run"]:
            transaction.set_rollback(True)
            self.stdout.write("Dry-run: no settings saved.")
