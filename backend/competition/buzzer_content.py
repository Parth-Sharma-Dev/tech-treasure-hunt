"""Private verified host content; the website accepts buzzes, never answers."""

import json
import re

from .models import BuzzerQuestion

STAGES = [
    {
        "number": 1,
        "title": "AI image recognition",
        "description": "Identify the AI-generated images.",
    },
    {
        "number": 2,
        "title": "Answer from keywords",
        "description": "Find the concept described by the keywords.",
    },
    {"number": 3, "title": "Word encoding", "description": "Decode the encoded word."},
    {
        "number": 4,
        "title": "Image abnormalities",
        "description": "Identify the abnormality in the image.",
    },
    {
        "number": 5,
        "title": "Progressive image guessing",
        "description": "Guess the image as the visible area expands.",
    },
]


def question_errors(question):
    errors = []
    if question.round.number != 5 or question.round.delivery_mode != "BUZZER":
        errors.append("Attach questions to a BUZZER Round 5 draft.")
    if type(question.stage) is not int or question.stage not in range(1, 6):
        errors.append("Choose a stage from 1 to 5.")
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,40}", question.public_id or ""):
        errors.append(
            "Use a stable question ID of up to 40 letters, digits, underscores or hyphens."
        )
    content = question.private_content
    if (
        not isinstance(content, dict)
        or not content.get("answer")
        or not isinstance(content.get("presentation_reference"), str)
        or not content["presentation_reference"].strip()
        or len(json.dumps(content).encode()) > 65536
    ):
        errors.append("Supply a private answer and presentation reference, at most 64 KiB.")
    if not question.version or not question.source_reference:
        errors.append("Record the question version and private source reference.")
    return errors


def questions_snapshot(round):
    return list(
        BuzzerQuestion.objects.filter(round=round)
        .order_by("stage", "pk")
        .values(
            "id",
            "public_id",
            "stage",
            "version",
            "source_reference",
            "private_content",
            "prepared_by_id",
            "verified_by_id",
        )
    )


def readiness_errors(round):
    errors = []
    questions = list(
        BuzzerQuestion.objects.filter(round=round).select_related("prepared_by", "verified_by")
    )
    if not 5 <= len(questions) <= 200 or {question.stage for question in questions} != set(
        range(1, 6)
    ):
        errors.append("Verify at least one question in each of the five stages, at most 200 total.")
    for question in questions:
        errors += question_errors(question)
        if (
            not question.verified_at
            or not question.prepared_by_id
            or not question.verified_by_id
            or question.prepared_by_id == question.verified_by_id
            or not all(
                user.is_staff and user.is_active
                for user in [question.prepared_by, question.verified_by]
            )
        ):
            errors.append(
                f"{question.public_id} needs independent active-staff content verification."
            )
        if not round.is_demo and (
            "PLACEHOLDER" in question.source_reference.upper()
            or question.source_reference.upper().startswith("PENDING")
        ):
            errors.append("Replace placeholder content references before real release.")
    for key, expected in {
        "buzzer_order_policy": "database_receipt_time",
        "buzzer_latency_policy": "no_compensation",
        "buzzer_equal_time_policy": "staff_review_required",
        "buzzer_early_policy": "reject_closed_window",
    }.items():
        if round.rules.get(key) != expected:
            errors.append(f"Configure the supported buzzer policy for {key}.")
    reference = round.rules.get("offline_rules_reference")
    if not isinstance(reference, str) or not reference.strip() or len(reference) > 200:
        errors.append("Record an approved offline scoring/answer/tie rules reference.")
    elif not round.is_demo and any(
        value in reference.upper() for value in ["PENDING", "PLACEHOLDER", "SYNTHETIC"]
    ):
        errors.append("Supply actual reviewed offline rules before real release.")
    if round.advancement_count is not None:
        errors.append("Round 5 is the final; leave advancement count empty.")
    return errors
