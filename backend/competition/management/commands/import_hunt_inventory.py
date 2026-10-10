import csv
import hashlib
import io
import json
import secrets
from pathlib import Path

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from competition.models import AuditEvent, EventContentSource, HuntCode, Mission, Round
from competition.rules import require_staff_permission

KEYWORDS = (
    "Supervised Learning",
    "Labelled Data",
    "Python",
    "List",
    "C",
    "Equality",
    "Sequence",
    "Logic",
    "Debugging",
    "Classification",
    "Spam",
    "Neural Network",
    "Weight",
    "Machine Learning",
    "Length",
    "Loop",
    "Dictionary",
    "Key-Value",
    "Reference",
    "List Comprehension",
    "Array",
    "Index",
    "Increment",
    "Character",
    "Pass by Value",
    "Pointer",
    "Memory Address",
    "Binary",
    "RGB",
    "Pixel",
    "Accuracy",
    "Imbalanced Data",
    "Training",
    "Testing",
    "Overfitting",
    "Mutable Default",
    "Double Pointer",
    "Switch",
    "Warmth",
    "Deduction",
)


class Command(BaseCommand):
    help = "Import an independent code CSV and private location inventory into a real R1 draft."

    def add_arguments(self, parser):
        parser.add_argument("--round", type=int, required=True)
        parser.add_argument("--csv", required=True)
        parser.add_argument("--locations", required=True)
        parser.add_argument("--actor", required=True)
        parser.add_argument("--expected-count", type=int, default=168)

    @transaction.atomic
    def handle(self, *args, **options):
        actor = get_user_model().objects.get(username=options["actor"])
        require_staff_permission(actor, "prepare_content")
        round = Round.objects.select_for_update().get(pk=options["round"])
        if round.number != 1 or round.is_demo or round.state != "DRAFT":
            raise CommandError("Choose an unpublished real Round 1 DRAFT.")
        raw = Path(options["csv"]).read_bytes()
        reader = csv.DictReader(io.StringIO(raw.decode("utf-8-sig"), newline=""))
        if reader.fieldnames != ["code"]:
            raise CommandError("CSV must have exactly one code column.")
        rows = list(reader)
        if any(set(row) != {"code"} or row["code"] is None for row in rows):
            raise CommandError("Malformed code row.")
        codes = [row["code"] for row in rows]
        if len(codes) != options["expected_count"] or len({c.upper() for c in codes}) != len(codes):
            raise CommandError("Code count or uniqueness does not match the expected inventory.")
        if any(len(c) != 6 or any(not 33 <= ord(ch) <= 126 for ch in c) for c in codes):
            raise CommandError("Codes require six printable ASCII characters without spaces.")
        locations_raw = Path(options["locations"]).read_bytes()
        locations = json.loads(locations_raw.decode("utf-8"))
        if (
            not isinstance(locations, list)
            or not locations
            or len(locations) > 25
            or any(
                not isinstance(loc, str) or not loc.strip() or len(loc) > 200 for loc in locations
            )
            or len(set(locations)) != len(locations)
        ):
            raise CommandError("Supply up to 25 distinct nonempty location names.")
        digest = hashlib.sha256(raw).hexdigest()
        source = EventContentSource.objects.filter(round=round, kind="CODE_POOL").first()
        if source and source.sha256 != digest:
            raise CommandError(
                "Different code pool already stored; preserve it and review a revision."
            )
        if source is None:
            source = EventContentSource.objects.create(
                round=round,
                kind="CODE_POOL",
                filename=Path(options["csv"]).name,
                sha256=digest,
                original_bytes=raw,
                content={
                    "count": len(codes),
                    "codes": codes,
                    "normalization": "ignore ASCII letter case; preserve punctuation",
                },
                prepared_by=actor,
            )
            for code in codes:
                HuntCode.objects.create(
                    round=round, source=source, code=code, keyword=secrets.choice(KEYWORDS)
                )
        elif set(HuntCode.objects.filter(round=round).values_list("code", flat=True)) != set(codes):
            raise CommandError(
                "Stored code rows differ from original; investigate before importing."
            )
        for number, location in enumerate(locations, 1):
            mission = Mission.objects.filter(round=round, public_id=f"MISSION-{number:02}").first()
            if mission and mission.clue_location != location:
                raise CommandError(
                    "Location order conflicts with existing missions; review the inventory."
                )
            if mission is None:
                Mission.objects.create(
                    round=round,
                    public_id=f"MISSION-{number:02}",
                    clue_location=location,
                    hint="",
                    qr_location="",
                    keyword="",
                    answer_verifiers=[],
                    prepared_by=actor,
                    available=False,
                )
        location_digest = hashlib.sha256(locations_raw).hexdigest()
        if not EventContentSource.objects.filter(
            round=round, kind="LOCATIONS", sha256=location_digest
        ).exists():
            EventContentSource.objects.create(
                round=round,
                kind="LOCATIONS",
                filename=Path(options["locations"]).name,
                sha256=location_digest,
                original_bytes=locations_raw,
                content={"locations": locations, "expected_total": 25},
                prepared_by=actor,
            )
        AuditEvent.objects.create(
            actor=actor,
            action="import_hunt_inventory",
            before={},
            after={
                "round_id": round.pk,
                "code_count": len(codes),
                "location_count": len(locations),
                "code_source_sha256": digest,
            },
            reason=(
                "Organizer supplied independent codes and locations; "
                "stored privately, without release."
            ),
        )
        self.stdout.write(f"Stored {len(codes)} independent codes and {len(locations)} locations.")
