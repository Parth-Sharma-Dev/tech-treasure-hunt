"""Audited transition of existing browser sessions to the single-session policy."""

from uuid import uuid4

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.db import transaction

from competition.models import Team
from competition.rules import require_staff_permission
from competition.sessions import active_sessions, revoke_session


class Command(BaseCommand):
    help = "Keep each team's most recently used browser and audit revocation of extra sessions."

    def add_arguments(self, parser):
        parser.add_argument("--actor", required=True)

    @transaction.atomic
    def handle(self, *args, **options):
        actor = get_user_model().objects.get(username=options["actor"])
        require_staff_permission(actor, "control_round")
        count = 0
        for team in Team.objects.select_for_update().order_by("pk"):
            sessions = list(active_sessions(team).order_by("-last_seen_at", "-pk"))
            for session in sessions[1:]:
                revoke_session(
                    team.pk,
                    session.pk,
                    actor,
                    str(uuid4()),
                    "Organizer policy: one active browser per team; "
                    "retain most recently used session.",
                )
                count += 1
        self.stdout.write(
            f"Revoked {count} extra sessions; retained session evidence and team results."
        )
