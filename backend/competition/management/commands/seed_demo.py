import json
import secrets
from pathlib import Path

from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from competition.answers import answer_digest
from competition.demo import demo_rules
from competition.models import Mission, Round, Team


class Command(BaseCommand):
    help = "Create fictional DRAFT rounds, teams and practice content in a local demo database."

    def add_arguments(self, parser):
        parser.add_argument("--credentials-file", default=".local/demo-credentials.json")

    @transaction.atomic
    def handle(self, *args, **options):
        if (
            not settings.DEBUG
            or Round.objects.filter(is_demo=False).exists()
            or Team.objects.filter(is_demo=False).exists()
        ):
            raise CommandError(
                "Demo seeds require DEBUG and a database containing only demo records."
            )
        credentials_path = Path(options["credentials_file"])
        if credentials_path.suffix != ".json":
            raise CommandError("The credentials file must use the .json extension.")
        existing_credentials = (
            json.loads(credentials_path.read_text()) if credentials_path.exists() else {}
        )
        credentials = {}
        user_model = get_user_model()

        def demo_user(username, staff=False):
            user, created = user_model.objects.get_or_create(
                username=username, defaults={"is_staff": staff}
            )
            if created:
                password = secrets.token_urlsafe(18)
                user.set_password(password)
                user.save()
                credentials[username] = password
            elif user.is_staff != staff:
                raise CommandError(f"Existing account {username} does not match the demo role.")
            return user

        maker = demo_user("DEMO-content", staff=True)
        verifier = demo_user("DEMO-verifier", staff=True)
        for user, codenames in (
            (maker, ["prepare_content", "control_round"]),
            (verifier, ["verify_evidence", "publish_results"]),
        ):
            user.user_permissions.add(
                *Permission.objects.filter(
                    content_type__app_label="competition", codename__in=codenames
                )
            )
        for index, name in enumerate(("Demo Loop Seekers", "Demo Stack Explorers"), start=1):
            code = f"DEMO-{index:02d}"
            user = demo_user(code)
            Team.objects.get_or_create(
                code=code,
                defaults={
                    "name": name,
                    "user": user,
                    "member_count": 3,
                    "is_demo": True,
                    "leader_name": "Demo leader",
                    "roster_reference": "synthetic-demo-roster",
                },
            )
        titles = [
            "Treasure hunt",
            "Quiz and puzzles",
            "Coding and debugging",
            "Faculty challenge",
            "Visual final",
        ]
        owners = {
            "technical_lead": maker.pk,
            "content_lead": maker.pk,
            "operations_lead": maker.pk,
            "adjudicator": maker.pk,
            "verifier": verifier.pk,
        }
        for number, title in enumerate(titles, start=1):
            Round.objects.get_or_create(
                number=number,
                attempt_no=1,
                defaults={
                    "title": title,
                    "is_demo": True,
                    "delivery_mode": Round.Delivery.ONLINE_HUNT
                    if number == 1
                    else Round.Delivery.EXTERNAL,
                    "advancement_count": 1 if number < 5 else None,
                    "owners": owners,
                    "rules_version": "demo-v1",
                    "rules": demo_rules(number),
                },
            )
        hunt = Round.objects.get(number=1, attempt_no=1)
        if hunt.state == Round.State.DRAFT:
            for public_id, hint, answer, keyword, practice in (
                (
                    "PRACTICE",
                    "Practice only: enter the four characters 0427.",
                    "0427",
                    "PRACTICE",
                    True,
                ),
                (
                    "DEMO-M01",
                    "Synthetic clue: two to the power of ten, as four digits.",
                    "1024",
                    "LOOP",
                    False,
                ),
                (
                    "DEMO-M02",
                    "Synthetic clue: write forty-two using four digits.",
                    "0042",
                    "STACK",
                    False,
                ),
            ):
                mission, created = Mission.objects.get_or_create(
                    round=hunt,
                    public_id=public_id,
                    defaults={
                        "hint": hint,
                        "keyword": keyword,
                        "is_practice": practice,
                        "qr_location": "Synthetic demo location",
                        "clue_location": "Synthetic demo location",
                        "volunteer_owner": maker,
                        "prepared_by": maker,
                    },
                )
                if created:
                    mission.answer_verifiers = [
                        {
                            "version": "demo-v1",
                            "digest": answer_digest(mission.pk, "demo-v1", answer),
                        }
                    ]
                    mission.save(update_fields=["answer_verifiers"])
        # Seeds never approve rules or attest to independent clue verification.
        if credentials:
            existing_credentials.update(credentials)
            credentials_path.parent.mkdir(parents=True, exist_ok=True)
            credentials_path.write_text(
                json.dumps(existing_credentials, indent=2), encoding="utf-8"
            )
        self.stdout.write(
            self.style.SUCCESS(
                "Demo seed complete; no rules or missions were approved by this command."
            )
        )
        if credentials:
            self.stdout.write(f"New demo credentials saved privately to {credentials_path}.")
