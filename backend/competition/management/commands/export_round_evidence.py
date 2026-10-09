import json
from pathlib import Path

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from competition.evidence import locked_evidence_round, make_bundle
from competition.results import require_result_view


class Command(BaseCommand):
    help = "Capture a private signed ended-round checkpoint; never overwrite an existing file."

    def add_arguments(self, parser):
        parser.add_argument("--round", required=True, type=int)
        parser.add_argument("--actor", required=True)
        parser.add_argument("--output", required=True)

    def handle(self, *args, **options):
        actor = get_user_model().objects.filter(username=options["actor"]).first()
        if actor is None:
            raise CommandError("Staff actor not found.")
        require_result_view(actor)
        with transaction.atomic():
            bundle = make_bundle(locked_evidence_round(options["round"]))
        path = Path(options["output"])
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("x", encoding="utf-8") as stream:
            json.dump(bundle, stream, indent=2)
        self.stdout.write(
            f"Private signed checkpoint saved to {path}. Keep signing keys separately."
        )
