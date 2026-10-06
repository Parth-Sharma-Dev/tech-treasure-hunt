import uuid

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError

from competition.api import ApiProblem
from competition.clock import control_round, database_now
from competition.models import Round
from competition.rules import require_staff_permission


class Command(BaseCommand):
    help = "Persist expired online rounds using an authorized staff actor; safe to repeat."

    def add_arguments(self, parser):
        parser.add_argument("--actor", required=True, help="Authorized controller username")

    def handle(self, *args, **options):
        actor = get_user_model().objects.filter(username=options["actor"]).first()
        if actor is None:
            raise CommandError("Controller not found.")
        require_staff_permission(actor, "control_round")
        expired = list(
            Round.objects.filter(
                state="LIVE", play_mode="ONLINE", deadline_at__lt=database_now()
            ).values_list("pk", "control_version")
        )
        ended = 0
        for round_id, version in expired:
            try:
                control_round(
                    round_id,
                    actor,
                    {
                        "action": "end",
                        "action_id": str(uuid.uuid4()),
                        "expected_version": version,
                        "reason": "Persist the expired active deadline.",
                    },
                )
            except ApiProblem as error:
                if error.code != "stale_control":
                    raise CommandError(str(error)) from error
            else:
                ended += 1
        self.stdout.write(f"Persisted {ended} expired rounds.")
