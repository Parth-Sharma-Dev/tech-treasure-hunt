import binascii
import zipfile

from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.management.base import BaseCommand, CommandError
from django.db import IntegrityError

from competition.event_transfer import export_package, import_package
from competition.rules import require_staff_permission


class Command(BaseCommand):
    help = "Export/import private initial real drafts without replacing accounts or event history."

    def add_arguments(self, parser):
        operation = parser.add_mutually_exclusive_group(required=True)
        operation.add_argument("--export", action="store_true")
        operation.add_argument("--import", dest="import_content", action="store_true")
        parser.add_argument("--file", required=True)
        parser.add_argument("--actor", required=True)
        parser.add_argument("--dry-run", action="store_true")

    def handle(self, *args, **options):
        try:
            actor = get_user_model().objects.get(username=options["actor"])
            require_staff_permission(actor, "prepare_content")
            if options["export"]:
                if options["dry_run"]:
                    raise CommandError("Dry-run is available for imports only.")
                payload = export_package(options["file"])
                self.stdout.write(
                    f"Private package written: {len(payload['rounds'])} rounds, "
                    f"{len(payload['missions'])} missions, {len(payload['codes'])} codes."
                )
            else:
                summary = import_package(options["file"], actor, options["dry_run"])
                label = "Dry-run passed (no records saved)" if options["dry_run"] else "Imported"
                self.stdout.write(f"{label}: {summary}")
        except (
            get_user_model().DoesNotExist,
            PermissionDenied,
            ValidationError,
            IntegrityError,
            OSError,
            ValueError,
            KeyError,
            TypeError,
            zipfile.BadZipFile,
            binascii.Error,
        ) as error:
            # Avoid printing private field values, source content or credential data.
            raise CommandError(
                f"Transfer failed ({type(error).__name__}); destination changes rolled back. "
                "Check permissions, package structure and conflicting records."
            ) from None
