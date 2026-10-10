import hashlib
import json
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.db.models import Max

from competition.models import AuditEvent, EventContentSource, FacultyProfile, Mission, Round
from competition.rules import require_staff_permission

TITLES = (
    "QR Mission Hunt",
    "Tech Quiz",
    "Crack The Code",
    "Faculty Interaction",
    "Reach The Treasure",
)
DELIVERIES = ("ONLINE_HUNT", "EXTERNAL", "CODING", "EXTERNAL", "BUZZER")


class Command(BaseCommand):
    help = "Store privately prepared real event content in unpublished DRAFT rounds."

    def add_arguments(self, parser):
        parser.add_argument("--manifest", required=True)
        parser.add_argument("--actor", required=True)

    @transaction.atomic
    def handle(self, *args, **options):
        from django.contrib.auth import get_user_model

        actor = get_user_model().objects.get(username=options["actor"])
        require_staff_permission(actor, "prepare_content")
        manifest = json.loads(Path(options["manifest"]).read_text(encoding="utf-8"))
        sources = []
        for source in manifest["sources"]:
            raw = Path(source["path"]).read_bytes()
            if hashlib.sha256(raw).hexdigest() != source["sha256"]:
                raise CommandError("Original file changed after extraction; extract again.")
            sources.append((source, raw))
        rounds = {}
        # Serialize with existing round records; never alter released/demo attempts.
        list(Round.objects.select_for_update().order_by("pk"))
        for number, (title, delivery) in enumerate(zip(TITLES, DELIVERIES, strict=True), 1):
            current = (
                Round.objects.filter(number=number, is_demo=False).order_by("-attempt_no").first()
            )
            if current and (current.state != "DRAFT" or current.title != title):
                raise CommandError("Real rounds already exist outside this draft import scope.")
            if current is None:
                attempt = (
                    Round.objects.filter(number=number).aggregate(n=Max("attempt_no"))["n"] or 0
                )
                current = Round.objects.create(
                    number=number,
                    attempt_no=attempt + 1,
                    title=title,
                    delivery_mode=delivery,
                    is_demo=False,
                )
            rounds[number] = current
        for source, raw in sources:
            round = rounds[source["round"]]
            if EventContentSource.objects.filter(
                round=round, kind=source["kind"], sha256=source["sha256"]
            ).exists():
                continue
            if EventContentSource.objects.filter(round=round, kind=source["kind"]).exists():
                raise CommandError(
                    "A different original is already imported; review a revision separately."
                )
            if source["kind"] == "RIDDLES":
                for item in source["content"]["missions"]:
                    if Mission.objects.filter(round=round, public_id=item["public_id"]).exists():
                        raise CommandError(
                            "Mission already exists; refusing to overwrite organizer edits."
                        )
                    Mission.objects.create(
                        round=round,
                        public_id=item["public_id"],
                        hint=item["riddle"],
                        clue_location=item["location"],
                        qr_location="",
                        keyword="",
                        answer_verifiers=[],
                        prepared_by=actor,
                        available=False,
                    )
            EventContentSource.objects.create(
                round=round,
                kind=source["kind"],
                filename=Path(source["path"]).name,
                sha256=source["sha256"],
                original_bytes=raw,
                content=source["content"],
                prepared_by=actor,
            )
        for item in manifest["faculty"]:
            if not FacultyProfile.objects.filter(is_demo=False, display_name=item["name"]).exists():
                FacultyProfile.objects.create(
                    display_name=item["name"],
                    role="CSE Department",
                    contact_channel=item["phone"],
                    is_demo=False,
                    visible=False,
                    consent_reference="",
                    prepared_by=actor,
                )
        AuditEvent.objects.create(
            actor=actor,
            action="import_event_content",
            before={},
            after={
                "round_ids": {str(n): r.pk for n, r in rounds.items()},
                "source_sha256": [s["sha256"] for s, _ in sources],
            },
            reason=(
                "Organizer supplied actual event content; "
                "stored privately without release or verification."
            ),
        )
        self.stdout.write("Stored real event drafts; no codes, publication or approval created.")
        self.stdout.write(str({n: r.pk for n, r in rounds.items()}))
