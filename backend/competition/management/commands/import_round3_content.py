import base64
import hashlib
import json
from pathlib import Path

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from competition.final_event_settings import COMMON
from competition.green_cards import SCHEMA
from competition.models import AuditEvent, CodingTask, EventContentSource, Round, RoundInformation
from competition.rules import OWNER_ROLES, require_staff_permission


class Command(BaseCommand):
    help = (
        "Import private Round 3 tasks and configure unpublished R3/R4 drafts; never release play."
    )

    def add_arguments(self, parser):
        parser.add_argument("--bundle", required=True)
        parser.add_argument("--actor", required=True)
        parser.add_argument("--verifier", required=True)
        parser.add_argument("--dry-run", action="store_true")

    @transaction.atomic
    def handle(self, *args, **options):
        from competition.coding_content import CATEGORY_POINTS, readiness_errors

        users = get_user_model()
        actor = users.objects.get(username=options["actor"])
        verifier = users.objects.get(username=options["verifier"])
        require_staff_permission(actor, "prepare_content")
        require_staff_permission(actor, "control_round")
        require_staff_permission(verifier, "verify_evidence")
        if actor.pk == verifier.pk:
            raise CommandError("Use distinct content and verifier accounts.")
        path = Path(options["bundle"])
        if path.stat().st_size > 2_000_000:
            raise CommandError("Private bundle exceeds 2 MB.")
        bundle = json.loads(path.read_text(encoding="utf-8"))
        if bundle.get("version") != 1 or len(bundle.get("tasks", [])) != 5:
            raise CommandError("Expected the supplied five-task bundle.")
        source = bundle["source"]
        raw = base64.b64decode(source["content_base64"], validate=True)
        if hashlib.sha256(raw).hexdigest() != source["sha256"]:
            raise CommandError("Original document checksum differs.")
        rounds = {}
        for number in (3, 4):
            round = (
                Round.objects.select_for_update()
                .filter(number=number, is_demo=False)
                .order_by("-attempt_no")
                .first()
            )
            if round is None or round.state != "DRAFT":
                raise CommandError("Both real Round 3 and Round 4 must remain DRAFT.")
            rounds[number] = round
        r3, r4 = rounds[3], rounds[4]
        existing = EventContentSource.objects.filter(round=r3, kind="CODING_PAPER").first()
        if existing and existing.sha256 != source["sha256"]:
            raise CommandError("A different paper is already retained; refusing replacement.")
        if CodingTask.objects.filter(round=r3).exists():
            raise CommandError("Coding tasks already exist; refusing to overwrite organizer edits.")
        r3.delivery_mode = "CODING"
        r3.active_budget_ms, r3.advancement_count = 2700000, 11
        r3.rules_version = "event-r3-20261013-v1"
        r3.rules = {
            **COMMON,
            **r3.rules,
            "allowed_tools": [
                "Lab Python 3.13.13",
                "Lab C compiler 15.2.0 / C99",
                "Contest submission website",
            ],
            "movement_policy": "Use the assigned supervised coding workstation.",
            "route_reference": f"{source['filename']}: workstation register",
            "delivery_instructions": bundle["instructions"],
            "submission_policy": "locked_final_with_cutoff_autofinalize",
            "ranking_policy": "score_correct_tasks_final_time",
            "qualification_tie_policy": "block_exact_ties",
            "one_workstation_per_team": True,
            "score_precision": 3,
            "language_versions": {"PYTHON": "3.13.13", "C": "Compiler 15.2.0; C99"},
        }
        r4.delivery_mode, r4.advancement_count = "EXTERNAL", 5
        r4.active_budget_ms = r4.active_budget_ms or 3600000
        r4.rules_version = "event-r4-green-card-20261013-v1"
        r4.rules = {
            **COMMON,
            **r4.rules,
            "allowed_tools": ["Faculty-supervised interview"],
            "movement_policy": "Follow the organizer's faculty interview instructions.",
            "delivery_instructions": (
                "11 qualified teams enter. Faculty interviews have no fixed question set "
                "or numerical criteria. Green Card yes/no determines qualification; "
                "up to five teams advance."
            ),
            "ranking_policy": "green_card_qualification",
            "score_schema": SCHEMA.copy(),
        }
        r4.rules.pop("faculty_panels", None)
        for round in rounds.values():
            round.owners = {
                role: verifier.pk if role == "verifier" else actor.pk for role in OWNER_ROLES
            }
            round.approved_by = round.approved_at = None
            round.approval_digest = ""
            round.rules_snapshot = {}
            round.save()
        fields = {
            "public_id",
            "category",
            "prompt",
            "starter_code",
            "languages",
            "points",
            "version",
            "private_rubric",
        }
        categories = []
        for item in bundle["tasks"]:
            if set(item) != fields:
                raise CommandError("Unexpected task fields.")
            if item["category"] not in CATEGORY_POINTS or str(item["points"]) != str(
                CATEGORY_POINTS[item["category"]]
            ):
                raise CommandError("Task category points do not match the approved paper.")
            categories.append(item["category"])
            task = CodingTask(round=r3, prepared_by=actor, **item)
            task.full_clean()
            task.save()
        if len(set(categories)) != 5:
            raise CommandError("Supply each of the five categories exactly once.")
        EventContentSource.objects.create(
            round=r3,
            kind="CODING_PAPER",
            filename=source["filename"],
            sha256=source["sha256"],
            original_bytes=raw,
            content={"tasks": bundle["tasks"]},
            prepared_by=actor,
        )
        from datetime import datetime
        from zoneinfo import ZoneInfo

        info, _ = RoundInformation.objects.get_or_create(round=r3)
        if info.published_at is not None:
            raise CommandError(
                "Round information is already published; preserve it for reviewed revision."
            )
        info.summary = "Crack the Code: 45 minutes, 100 marks; top 11 qualify for Round 4."
        info.instructions = bundle["instructions"]
        info.scheduled_start = datetime(2026, 10, 13, 12, 0, tzinfo=ZoneInfo("Asia/Kolkata"))
        info.scheduled_end = datetime(2026, 10, 13, 12, 45, tzinfo=ZoneInfo("Asia/Kolkata"))
        info.prepared_by = actor
        info.full_clean()
        info.save()
        AuditEvent.objects.create(
            actor=actor,
            action="import_round3_content",
            reason="Organizer supplied Round 3 paper; cut 11; Round 4 Green Cards only, cut 5.",
            after={
                "round3_id": r3.pk,
                "round4_id": r4.pk,
                "source_sha256": source["sha256"],
                "task_count": 5,
            },
        )
        self.stdout.write(
            f"Prepared R3 {r3.pk}: 5 tasks, 100 marks, 11 qualifiers. "
            f"R4 {r4.pk}: Green Card only, up to 5 qualifiers."
        )
        self.stdout.write("Readiness checks: " + "; ".join(readiness_errors(r3)))
        self.stdout.write(
            "Faculty identities preserved. Tasks, rules and public information "
            "require independent verification/publication."
        )
        if options["dry_run"]:
            transaction.set_rollback(True)
            self.stdout.write("Dry run rolled back: no database records changed.")
