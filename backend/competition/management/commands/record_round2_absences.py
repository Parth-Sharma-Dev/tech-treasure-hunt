"""Prepare and independently commit explicit Round 2 attendance evidence."""

import json
import uuid

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError

from competition.external_scores import commit_import, validate_import
from competition.models import Round
from competition.wayground import VERSION, is_wayground


class Command(BaseCommand):
    help = "Prepare absent-team evidence or independently commit its reviewed batch."

    def add_arguments(self, parser):
        parser.add_argument("--round-id", type=int, required=True)
        parser.add_argument("--actor", required=True)
        parser.add_argument("--reason", required=True)
        group = parser.add_mutually_exclusive_group(required=True)
        group.add_argument("--teams", nargs="+")
        group.add_argument("--batch-id", type=int)
        parser.add_argument("--attendance-reference")
        parser.add_argument("--review-confirmed", action="store_true")

    def handle(self, *args, **options):
        actor = get_user_model().objects.filter(username=options["actor"]).first()
        if actor is None:
            raise CommandError("Actor not found.")
        round = Round.objects.get(pk=options["round_id"])
        if round.is_demo or not is_wayground(round) or round.state not in ("ENDED", "PROVISIONAL"):
            raise CommandError("Select an ended real Wayground Round 2.")
        if round.rules_snapshot.get("advancement_count") != 20:
            raise CommandError("Frozen advancement count must be the approved 20.")
        data = {"action_id": str(uuid.uuid4()), "reason": options["reason"]}
        if options["teams"]:
            if not options["attendance_reference"]:
                raise CommandError("Supply the attendance evidence reference.")
            data.update(
                schema_version=VERSION,
                rows=[
                    {
                        "team_code": code,
                        "absent": True,
                        "absence_reason": options["reason"],
                        "attendance_reference": options["attendance_reference"],
                    }
                    for code in options["teams"]
                ],
            )
            result = validate_import(round.pk, actor, data)
            self.stdout.write(json.dumps(result, indent=2))
            if result["errors"]:
                raise CommandError("Absence batch failed validation; no scores committed.")
            self.stdout.write(
                "Prepared only. A different verifier must review and commit this batch."
            )
        else:
            from competition.models import ImportBatch

            batch = ImportBatch.objects.get(pk=options["batch_id"], round=round)
            if not batch.source_rows or any(
                row.get("absent") is not True for row in batch.source_rows
            ):
                raise CommandError("This command commits absence batches only.")
            if not options["review_confirmed"]:
                raise CommandError("Independent verifier must confirm attendance review.")
            data.update(batch_id=batch.pk, evidence_confirmed=True)
            result = commit_import(round.pk, actor, data)
            self.stdout.write(json.dumps(result))
