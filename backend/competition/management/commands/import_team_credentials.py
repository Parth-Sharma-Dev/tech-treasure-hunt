import csv

from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.management.base import BaseCommand, CommandError
from django.db import IntegrityError
from django.views.decorators.debug import sensitive_variables

from competition.api import ApiProblem
from competition.team_import import import_teams


class Command(BaseCommand):
    help = "Import a private official team/leader/email/password CSV with Django password hashes."

    def add_arguments(self, parser):
        parser.add_argument("--csv", required=True)
        parser.add_argument("--actor", default="parth")
        parser.add_argument("--verifier", default="verifier")
        parser.add_argument("--member-count", type=int, choices=[3, 4], required=True)
        parser.add_argument("--expected-count", type=int, default=110)
        parser.add_argument("--review-confirmed", action="store_true")
        parser.add_argument("--dry-run", action="store_true")

    @sensitive_variables()
    def handle(self, *args, **options):
        if not options["dry_run"] and not options["review_confirmed"]:
            raise CommandError(
                "Review the official file with the verifier, then use --review-confirmed."
            )
        users = get_user_model()
        try:
            actor = users.objects.get(username=options["actor"])
            verifier = users.objects.get(username=options["verifier"])
            count = import_teams(
                options["csv"],
                actor,
                verifier,
                options["member_count"],
                options["expected_count"],
                options["dry_run"],
            )
        except ApiProblem as error:
            raise CommandError(f"Import stopped ({error.code}); all writes rolled back.") from None
        except (
            users.DoesNotExist,
            PermissionDenied,
            ValidationError,
            IntegrityError,
            OSError,
            UnicodeError,
            csv.Error,
            ValueError,
        ) as error:
            # Never dump private rows or DB exception details to a deployment log.
            raise CommandError(
                f"Import stopped ({type(error).__name__}); check input, accounts and permissions. "
                "All writes rolled back."
            ) from None
        label = "Dry-run passed; no records saved" if options["dry_run"] else "Imported"
        self.stdout.write(
            f"{label}: {count} real teams, leader emails and Django-hashed passwords."
        )
