import hashlib
import uuid
from io import BytesIO

from django.contrib.auth import get_user_model
from django.core.files.base import ContentFile
from django.core.management.base import BaseCommand, CommandError
from PIL import Image

from competition.mission_images import private_image_storage
from competition.rules import require_staff_permission


class Command(BaseCommand):
    help = "Check private image storage write/read/delete using a new disposable PNG."

    def add_arguments(self, parser):
        parser.add_argument("--actor", default="parth")

    def handle(self, *args, **options):
        users = get_user_model()
        try:
            actor = users.objects.get(username=options["actor"])
        except users.DoesNotExist:
            raise CommandError("Content staff account not found.") from None
        require_staff_permission(actor, "prepare_content")
        output = BytesIO()
        Image.new("RGB", (2, 2), "white").save(output, format="PNG")
        content = output.getvalue()
        storage, name = private_image_storage(), None
        try:
            name = storage.save(f"deployment-checks/{uuid.uuid4().hex}.png", ContentFile(content))
            with storage.open(name, "rb") as stream:
                received = stream.read(len(content) + 1)
            if hashlib.sha256(received).digest() != hashlib.sha256(content).digest():
                raise CommandError("Private storage read-back checksum differs.")
        except Exception as error:
            raise CommandError(
                f"Private storage check failed ({type(error).__name__}); check managed identity, "
                "Blob permissions, account/container settings and network access."
            ) from None
        finally:
            if name:
                try:
                    storage.delete(name)
                except Exception:
                    self.stderr.write(
                        "Disposable probe cleanup failed; remove deployment-checks probe privately."
                    )
        self.stdout.write("Private image storage write/read passed; no mission records changed.")
