from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from competition.demo import demo_rules
from competition.models import AuditEvent, Round
from competition.rules import require_staff_permission


class Command(BaseCommand):
    help = "Prepare unsigned external demo schemas; preserve released rounds and actual evidence."

    def add_arguments(self, parser):
        parser.add_argument("--actor", default="DEMO-content")

    @transaction.atomic
    def handle(self, *args, **options):
        if not settings.DEBUG:
            raise CommandError("External demo preparation requires DEBUG.")
        actor = get_user_model().objects.filter(username=options["actor"]).first()
        if not actor:
            raise CommandError("Content staff account not found.")
        require_staff_permission(actor, "prepare_content")
        for number in [2, 4]:
            round = (
                Round.objects.select_for_update()
                .filter(number=number, is_demo=True)
                .order_by("-attempt_no")
                .first()
            )
            if not round or round.state != "DRAFT":
                self.stdout.write(f"Round {number}: released or absent attempt preserved.")
                continue
            if round.rules.get("score_schema", {}).get("version") == f"round{number}-v1":
                self.stdout.write(f"Round {number}: existing external configuration preserved.")
                continue
            previous = round.rules
            round.delivery_mode = "EXTERNAL"
            round.rules_version = f"demo-external-{number}-v1"
            round.rules = {**round.rules, "qualification_tie_policy": "supervised_reserve_question"}
            if number == 2:
                round.rules.update(
                    {key: demo_rules(2)[key] for key in ["ranking_policy", "score_schema"]}
                )
                round.active_budget_ms = 2_700_000
            else:
                round.rules.update(
                    {
                        "ranking_policy": "weighted_faculty_criteria",
                        "score_schema": {
                            "version": "round4-v1",
                            "max_score": "100",
                            "rounding": "half_up_3",
                        },
                        "faculty_panels": [],
                    }
                )
                round.active_budget_ms = 3_600_000
            round.approved_by = None
            round.approved_at = None
            round.approval_digest = ""
            round.save()
            AuditEvent.objects.create(
                actor=actor,
                action="prepare_external_demo",
                before={"rules": previous},
                after={"round_id": round.pk, "rules": round.rules},
                reason="Unsigned rehearsal schema; no roster, faculty or qualification invented.",
            )
            self.stdout.write(
                f"Round {number}: unsigned schema prepared; independent review is required."
            )
