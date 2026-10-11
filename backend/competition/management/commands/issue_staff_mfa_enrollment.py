from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError

from competition.mfa import issue_enrollment


class Command(BaseCommand):
    help = "Issue a private 30-minute, one-use staff MFA enrollment code from the trusted console."

    def add_arguments(self, parser):
        parser.add_argument("--username", required=True)
        parser.add_argument("--actor", required=True)
        parser.add_argument("--reason", required=True)

    def handle(self, *args, **options):
        users = get_user_model()
        try:
            user = users.objects.get(username=options["username"])
            actor = users.objects.get(username=options["actor"])
            code = issue_enrollment(user, actor, options["reason"])
        except (users.DoesNotExist, ValidationError) as error:
            raise CommandError(str(error)) from None
        self.stdout.write("Enter this private code at /staff-mfa/enroll/ within 30 minutes:")
        self.stdout.write(code)
