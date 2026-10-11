"""Bounded, private image clues with content hashes retained in competition evidence."""

import hashlib
import re
import uuid
import warnings
from io import BytesIO

from azure.core.exceptions import AzureError
from django.core.exceptions import ImproperlyConfigured, ValidationError
from django.core.files.base import ContentFile
from django.core.files.storage import FileSystemStorage, storages
from django.http import HttpResponse
from PIL import Image, ImageOps, UnidentifiedImageError
from storages.backends.azure_storage import AzureStorage

from .api import ApiProblem

MAX_UPLOAD_BYTES = 5 * 1024 * 1024
MAX_STORED_BYTES = 2 * 1024 * 1024
MAX_PIXELS = 8_000_000


class PrivateFileStorage(FileSystemStorage):
    def url(self, name):
        raise ValueError("Mission images must be served through the authorized image endpoint.")


class PrivateAzureStorage(AzureStorage):
    def check_config(self):
        if not self.account_name or not self.azure_container:
            raise ImproperlyConfigured(
                "Configure the private Azure mission image account/container."
            )

    def exists(self, name):
        self.check_config()
        return super().exists(name)

    def _open(self, name, mode="rb"):
        self.check_config()
        return super()._open(name, mode)

    def url(self, name, *args, **kwargs):
        raise ValueError("Mission images must be served through the authorized image endpoint.")


def private_image_storage():
    return storages["mission_images"]


def normalize_upload(upload):
    if upload.size > MAX_UPLOAD_BYTES:
        raise ValidationError("Use a JPEG, PNG or WebP file no larger than 5 MiB.")
    raw = upload.read(MAX_UPLOAD_BYTES + 1)
    if len(raw) > MAX_UPLOAD_BYTES:
        raise ValidationError("The image upload exceeds 5 MiB.")
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(BytesIO(raw), formats=["JPEG", "PNG", "WEBP"]) as image:
                width, height = image.size
                if width > 4096 or height > 4096 or width * height > MAX_PIXELS:
                    raise ValidationError(
                        "Use an image up to 4096 pixels per side and 8 megapixels."
                    )
                if getattr(image, "n_frames", 1) != 1:
                    raise ValidationError("Use a single still image, not an animation.")
                image.load()
                image = ImageOps.exif_transpose(image)
                has_alpha = "A" in image.getbands() or "transparency" in image.info
                image = image.convert("RGBA" if has_alpha else "RGB")
                output = BytesIO()
                # Re-encoding drops original names, EXIF, comments and other metadata.
                image.info.clear()
                image.save(output, format="PNG")
                content = output.getvalue()
                width, height = image.size
    except (
        UnidentifiedImageError,
        OSError,
        ValueError,
        Image.DecompressionBombError,
        Image.DecompressionBombWarning,
    ):
        raise ValidationError("Upload a valid, bounded JPEG, PNG or WebP image.") from None
    if len(content) > MAX_STORED_BYTES:
        raise ValidationError("The normalized image exceeds 2 MiB; reduce its dimensions.")
    return {
        "file": ContentFile(content, name=f"{uuid.uuid4().hex}.png"),
        "sha256": hashlib.sha256(content).hexdigest(),
        "width": width,
        "height": height,
    }


def image_errors(mission):
    errors = []
    if mission.clue_type == "IMAGE" and mission.available and not mission.clue_image:
        errors.append("An available image mission needs an uploaded clue image.")
    if mission.clue_image:
        if mission.clue_type != "IMAGE" or mission.round.number != 1 or mission.is_practice:
            errors.append("Image clues belong to competitive Round 1 image missions.")
        if not mission.image_alt.strip():
            errors.append("Supply approved alternative text for the image clue.")
        if not re.fullmatch(r"[a-f0-9]{64}", mission.image_sha256):
            errors.append("Upload the image through the mission form to record its checksum.")
        if not (0 < mission.image_width <= 4096 and 0 < mission.image_height <= 4096):
            errors.append("The image dimensions are invalid.")
        elif mission.image_width * mission.image_height > MAX_PIXELS:
            errors.append("The image exceeds 8 megapixels.")
    return errors


def verified_image_bytes(mission):
    if not mission.clue_image:
        raise ValidationError("No image is attached to this mission.")
    with mission.clue_image.open("rb") as stream:
        content = stream.read(MAX_STORED_BYTES + 1)
    if (
        len(content) > MAX_STORED_BYTES
        or hashlib.sha256(content).hexdigest() != mission.image_sha256
    ):
        raise ValidationError("The stored image differs from its recorded checksum.")
    return content


def image_response(mission):
    try:
        content = verified_image_bytes(mission)
    except (OSError, ValidationError, AzureError, ImproperlyConfigured):
        raise ApiProblem(
            "image_unavailable", "The clue image is temporarily unavailable.", 503
        ) from None
    response = HttpResponse(content, content_type="image/png")
    response["Content-Disposition"] = 'inline; filename="clue.png"'
    response["Cache-Control"] = "no-store"
    response["Vary"] = "Cookie"
    response["X-Content-Type-Options"] = "nosniff"
    return response
