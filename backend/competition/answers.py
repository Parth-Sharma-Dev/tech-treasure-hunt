import hashlib
import hmac
import re

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured, ValidationError


def answer_digest(mission_id, version, answer):
    if not isinstance(answer, str) or re.fullmatch(r"[0-9]{4}", answer) is None:
        raise ValidationError("Answers must contain exactly four ASCII digits.")
    if not settings.ANSWER_HMAC_KEY:
        raise ImproperlyConfigured("ANSWER_HMAC_KEY must be configured.")
    payload = f"mission:{mission_id}:version:{version}:answer:{answer}".encode()
    return hmac.new(settings.ANSWER_HMAC_KEY.encode(), payload, hashlib.sha256).hexdigest()
