"""Prepare the real Round 5 draft from a private PPT manifest; never fake verification."""

import hashlib
import json
import os
from pathlib import Path


def setup(path, dry_run=True, actor_name="parth", verifier_name="verifier"):
    from competition.buzzer_scoring_rules import PENALTY_CONTRACT
    from competition.models import AuditEvent, BuzzerQuestion, EventContentSource, Round
    from competition.rules import OWNER_ROLES, require_staff_permission
    from django.contrib.auth import get_user_model
    from django.db import transaction

    raw = Path(path).read_bytes()
    if len(raw) > 1_000_000:
        raise ValueError("Manifest exceeds 1 MB.")
    data = json.loads(raw)
    if data["rules"]["score_schema"] != PENALTY_CONTRACT:
        raise ValueError(
            "Use the confirmed v4 scoring; no unexpected points or penalties."
        )
    questions = data["questions"]
    if len(questions) != 25 or any(
        sum(q["stage"] == stage for q in questions) != 5 for stage in range(1, 6)
    ):
        raise ValueError("Provide exactly five questions in each of five stages.")
    if len({q["public_id"] for q in questions}) != 25:
        raise ValueError("Question IDs must be distinct.")
    with transaction.atomic():
        users = get_user_model().objects
        actor, verifier = (
            users.get(username=actor_name),
            users.get(username=verifier_name),
        )
        require_staff_permission(actor, "prepare_content")
        require_staff_permission(actor, "control_round")
        require_staff_permission(verifier, "verify_evidence")
        if actor.pk == verifier.pk:
            raise ValueError("Content and verification require different staff.")
        round = (
            Round.objects.select_for_update()
            .filter(number=5, is_demo=False)
            .order_by("-attempt_no")
            .first()
        )
        if round is None or round.state != "DRAFT":
            raise ValueError(
                "Use the latest real Round 5 DRAFT; do not reset released attempts."
            )
        if BuzzerQuestion.objects.filter(round=round).exists():
            raise ValueError(
                "Questions already exist; refusing to overwrite organizer content."
            )
        round.delivery_mode = "BUZZER"
        round.advancement_count = None
        round.rules_version = "event-r5-ppt-penalties-20261013-v1"
        round.rules = data["rules"]
        round.owners = {
            role: verifier.pk if role == "verifier" else actor.pk
            for role in OWNER_ROLES
        }
        round.approved_by = round.approved_at = None
        round.approval_digest = ""
        round.save()
        fields = {
            "public_id",
            "stage",
            "version",
            "source_reference",
            "private_content",
        }
        for row in questions:
            if set(row) != fields:
                raise ValueError("Unexpected question fields.")
            question = BuzzerQuestion(round=round, prepared_by=actor, **row)
            question.full_clean()
            question.save()
        checksum = hashlib.sha256(raw).hexdigest()
        EventContentSource.objects.create(
            round=round,
            kind="R5_PPT_MANIFEST",
            filename=Path(path).name,
            sha256=checksum,
            original_bytes=raw,
            content=data,
            prepared_by=actor,
        )
        AuditEvent.objects.create(
            actor=actor,
            action="setup_round5_ppt",
            reason="Organizer supplied presentation; configure v4 penalties and 25 private question references.",
            after={
                "round_id": round.pk,
                "question_count": 25,
                "manifest_sha256": checksum,
                "ppt_sha256": data["source"]["sha256"],
            },
        )
        if dry_run:
            transaction.set_rollback(True)
        return {
            "round_id": round.pk,
            "dry_run": dry_run,
            "question_count": 25,
            "verification": "Required: actual verifier reviews all 25 PPT questions and rule changes.",
            "duration_ms": round.active_budget_ms,
            "state": "DRAFT",
        }


if __name__ == "__main__":
    from django.db import connection

    if (
        connection.settings_dict["NAME"] != "treasure_hunt"
        or connection.settings_dict["HOST"]
        != "tth-event-db-parth.postgres.database.azure.com"
    ):
        raise ValueError(
            "Select the original production database before applying PPT setup."
        )
    print(
        json.dumps(
            setup(
                os.environ.get(
                    "TTH_R5_MANIFEST",
                    "/home/site/private-transfer/round5-ppt-setup.json",
                ),
                dry_run=os.environ.get("TTH_R5_DRY_RUN", "1") == "1",
            ),
            indent=2,
        )
    )
