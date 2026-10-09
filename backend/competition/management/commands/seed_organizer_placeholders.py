"""Editable, unpublished organizer data for local rehearsal only."""

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from competition.models import AuditEvent, FacultyProfile, Round, RoundInformation
from competition.roster import locked_roster
from competition.rules import require_staff_permission


class Command(BaseCommand):
    help = "Create labeled demo faculty/logistics drafts without publishing or assigning panels."

    def add_arguments(self, parser):
        parser.add_argument("--actor", default="DEMO-content")

    @transaction.atomic
    def handle(self, *args, **options):
        if not settings.DEBUG:
            raise CommandError("Organizer placeholders require local DEBUG mode.")
        actor = get_user_model().objects.filter(username=options["actor"]).first()
        if not actor:
            raise CommandError("Content staff account not found.")
        require_staff_permission(actor, "prepare_content")
        rounds, _ = locked_roster(True)
        created_ids = []
        latest = {}
        for round in sorted(rounds, key=lambda item: item.attempt_no):
            latest[round.number] = round
        for number, round in latest.items():
            if number not in [1, 2, 3, 4] or round.state != Round.State.DRAFT:
                continue
            information, created = RoundInformation.objects.get_or_create(
                round=round,
                defaults={
                    "prepared_by": actor,
                    "summary": f"PLACEHOLDER — Round {number} awaits organizer approval.",
                    "venue": "PLACEHOLDER — venue to be confirmed",
                    "instructions": "PLACEHOLDER — approved instructions to be supplied.",
                    "contacts": [
                        {
                            "name": "PLACEHOLDER — organizer name",
                            "role": "Event help",
                            "location": "Help desk to be confirmed",
                            "channel": "To be announced",
                        }
                    ],
                },
            )
            if created:
                AuditEvent.objects.create(
                    actor=actor,
                    action="prepare_information_placeholder",
                    after={"round_id": round.pk, "information_id": information.pk},
                    reason="Unpublished synthetic placeholder; actual logistics require review.",
                )
        if latest.get(4) and latest[4].state == Round.State.DRAFT:
            retained_slots = {}
            for audit in AuditEvent.objects.filter(
                action="prepare_faculty_placeholders", after__round_id=latest[4].pk
            ).order_by("pk"):
                retained_slots.update(audit.after.get("faculty_slots", {}))
                # Initial local rehearsal checkpoints recorded the six IDs in slot order.
                if not retained_slots and len(audit.after.get("faculty_ids", [])) == 6:
                    retained_slots.update(
                        zip(
                            [f"{panel}-{slot}" for panel in ["A", "B"] for slot in range(1, 4)],
                            audit.after["faculty_ids"],
                            strict=True,
                        )
                    )
            faculty_slots = {}
            for panel in ["A", "B"]:
                for slot in range(1, 4):
                    slot_key = f"{panel}-{slot}"
                    retained = retained_slots.get(slot_key)
                    if (
                        retained
                        and FacultyProfile.objects.filter(pk=retained, is_demo=True).exists()
                    ):
                        faculty_slots[slot_key] = retained
                        continue
                    profile, created = FacultyProfile.objects.get_or_create(
                        is_demo=True,
                        display_name=f"PLACEHOLDER — Panel {panel} faculty {slot}",
                        defaults={
                            "role": "Contest faculty — assignment pending",
                            "location": "PLACEHOLDER — interview venue",
                            "contact_channel": "PLACEHOLDER — approved contact pending",
                            "consent_reference": "",
                            "photo_url": "",
                            "prepared_by": actor,
                            "visible": False,
                        },
                    )
                    if created:
                        created_ids.append(profile.pk)
                    faculty_slots[slot_key] = profile.pk
            if created_ids:
                AuditEvent.objects.create(
                    actor=actor,
                    action="prepare_faculty_placeholders",
                    after={
                        "round_id": latest[4].pk,
                        "faculty_ids": created_ids,
                        "faculty_slots": faculty_slots,
                    },
                    reason="Unpublished faculty placeholders; consent and assignments pending.",
                )
        self.stdout.write(
            f"Created {len(created_ids)} faculty drafts. Existing data preserved; "
            "schedules, consent, panel assignments and publications remain pending."
        )
