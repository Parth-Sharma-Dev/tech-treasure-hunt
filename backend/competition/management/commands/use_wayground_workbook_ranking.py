import uuid

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError

from competition.external_scores import commit_import, current_scores, validate_import
from competition.models import ImportBatch, Round
from competition.wayground import VERSION, is_wayground


class Command(BaseCommand):
    help = "Prepare or independently commit a correction using the retained workbook Rank column."

    def add_arguments(self, parser):
        parser.add_argument("--round-id", type=int, required=True)
        parser.add_argument("--actor", required=True)
        parser.add_argument("--reason", required=True)
        group = parser.add_mutually_exclusive_group(required=True)
        group.add_argument("--prepare", action="store_true")
        group.add_argument("--batch-id", type=int)
        parser.add_argument("--decision-reference")
        parser.add_argument("--review-confirmed", action="store_true")

    def handle(self, *args, **options):
        import json

        actor = get_user_model().objects.filter(username=options["actor"]).first()
        if actor is None:
            raise CommandError("Actor not found.")
        round = Round.objects.get(pk=options["round_id"])
        if round.is_demo or not is_wayground(round) or round.state not in ("ENDED", "PROVISIONAL"):
            raise CommandError(
                "Select an ended real Wayground Round 2; finalized results are protected."
            )
        if round.rules_snapshot.get("advancement_count") != 20:
            raise CommandError("Frozen advancement count must remain 20.")
        data = {"action_id": str(uuid.uuid4()), "reason": options["reason"]}
        if options["prepare"]:
            if not options["decision_reference"]:
                raise CommandError("Supply the organizer's ranking-change decision reference.")
            scores = [
                r for r in current_scores(round).values() if r.tie_metrics.get("absent") is not True
            ]
            batch_ids = {r.import_batch_id for r in scores}
            if not scores or len(batch_ids) != 1:
                raise CommandError(
                    "Expected all participant scores from one committed report batch."
                )
            original = ImportBatch.objects.get(pk=next(iter(batch_ids)), round=round)
            if not original.committed_at:
                raise CommandError("Original score batch is not committed.")
            rows = []
            for source in original.source_rows:
                if "report_id" not in source:
                    raise CommandError("The score source must be original workbook mappings.")
                rows.append(
                    {
                        **source,
                        "use_workbook_rank": True,
                        "ranking_change_reference": options["decision_reference"],
                    }
                )
            result = validate_import(
                round.pk,
                actor,
                {
                    **data,
                    "schema_version": VERSION,
                    "rows": rows,
                },
            )
            self.stdout.write(json.dumps(result, indent=2))
            if result["errors"]:
                raise CommandError("Ranking correction failed validation. No scores committed.")
            self.stdout.write(
                "Prepared only. Have a different verifier review and commit the correction."
            )
        else:
            batch = ImportBatch.objects.get(pk=options["batch_id"], round=round)
            if not batch.source_rows or any(
                row.get("use_workbook_rank") is not True for row in batch.source_rows
            ):
                raise CommandError("Select a workbook-ranking correction batch.")
            if not options["review_confirmed"]:
                raise CommandError(
                    "Independent verifier must confirm the ranking decision and source review."
                )
            result = commit_import(
                round.pk,
                actor,
                {
                    **data,
                    "batch_id": batch.pk,
                    "evidence_confirmed": True,
                },
            )
            self.stdout.write(json.dumps(result))
