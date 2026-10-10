import hashlib
import hmac
import re

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured, ValidationError

NEW_FORMAT = "six_ascii_alphanumeric"
LEGACY_FORMAT = "four_ascii_digits"


def answer_format(round):
    return round.rules_snapshot.get("rules", round.rules).get("answer_format", LEGACY_FORMAT)


def normalize_answer(answer, format=None):
    pattern = (
        r"[0-9]{4}"
        if format == LEGACY_FORMAT
        else (r"[A-Za-z0-9]{6}" if format == NEW_FORMAT else r"(?:[0-9]{4}|[A-Za-z0-9]{6})")
    )
    if not isinstance(answer, str) or re.fullmatch(pattern, answer) is None:
        raise ValidationError(
            "Enter exactly six ASCII letters or digits."
            if format != LEGACY_FORMAT
            else "Enter exactly four ASCII digits."
        )
    return answer.upper()


def validate_answer(round, answer):
    from .api import ApiProblem

    try:
        return normalize_answer(answer, answer_format(round))
    except ValidationError as error:
        raise ApiProblem("invalid_format", error.messages[0]) from None


def answer_digest(mission_id, version, answer):
    answer = normalize_answer(answer)
    if not settings.ANSWER_HMAC_KEY:
        raise ImproperlyConfigured("ANSWER_HMAC_KEY must be configured.")
    payload = f"mission:{mission_id}:version:{version}:answer:{answer}".encode()
    return hmac.new(settings.ANSWER_HMAC_KEY.encode(), payload, hashlib.sha256).hexdigest()
