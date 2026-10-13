"""Apply a private, checksum-guarded coding-task revision from Django shell.

Upload this script and its private JSON separately; no app deployment is needed.
Run with manage.py shell/runpy and TTH_CODING_REVISION pointing to the JSON.
"""

import hashlib
import json
import os
from pathlib import Path


def apply_revision(path, actor_name, dry_run=False):
    from competition.models import AuditEvent, CodingTask, EventContentSource, Round
    from competition.rules import require_staff_permission
    from django.contrib.auth import get_user_model
    from django.db import transaction

    raw = Path(path).read_bytes()
    if len(raw) > 100_000:
        raise ValueError("Revision exceeds 100 KB.")
    data = json.loads(raw)
    if set(data) != {
        "public_id",
        "expected_prompt_sha256",
        "prompt",
        "private_rubric",
        "version",
    }:
        raise ValueError("Unexpected revision fields.")
    with transaction.atomic():
        actor = get_user_model().objects.get(username=actor_name)
        require_staff_permission(actor, "prepare_content")
        round = (
            Round.objects.select_for_update()
            .filter(number=3, is_demo=False)
            .order_by("-attempt_no")
            .first()
        )
        if round is None or round.state != "DRAFT" or round.delivery_mode != "CODING":
            raise ValueError(
                "Only the latest real CODING Round 3 DRAFT can be revised."
            )
        task = CodingTask.objects.get(round=round, public_id=data["public_id"])
        if (
            task.version == data["version"]
            and task.prompt == data["prompt"]
            and task.private_rubric == data["private_rubric"]
        ):
            return "Revision already applied; nothing changed."
        if (
            hashlib.sha256(task.prompt.encode()).hexdigest()
            != data["expected_prompt_sha256"]
        ):
            raise ValueError(
                "The task differs from the supplied paper; refusing to overwrite edits."
            )
        before = {
            "task_id": task.pk,
            "version": task.version,
            "prompt_sha256": data["expected_prompt_sha256"],
        }
        task.prompt, task.private_rubric, task.version = (
            data["prompt"],
            data["private_rubric"],
            data["version"],
        )
        task.prepared_by = actor
        task.full_clean()
        task.save()
        round.approved_by = round.approved_at = None
        round.approval_digest = ""
        round.save()
        checksum = hashlib.sha256(raw).hexdigest()
        EventContentSource.objects.create(
            round=round,
            kind="CODING_TASK_REVISION",
            filename=Path(path).name,
            sha256=checksum,
            original_bytes=raw,
            content=data,
            prepared_by=actor,
        )
        AuditEvent.objects.create(
            actor=actor,
            action="revise_coding_task",
            before=before,
            after={
                "task_id": task.pk,
                "version": task.version,
                "revision_sha256": checksum,
            },
            reason="Organizer replaces fixed-output task with general code reasoning; marks preserved.",
        )
        if dry_run:
            transaction.set_rollback(True)
            return "Dry run passed and rolled back. Marks/languages/category preserved."
        return "Task revised. Existing verification and round approval cleared; independently verify again."


if __name__ == "__main__":
    print(
        apply_revision(
            os.environ.get(
                "TTH_CODING_REVISION",
                "/home/site/private-transfer/round3-q1-revision.json",
            ),
            os.environ.get("TTH_CODING_ACTOR", "parth"),
            os.environ.get("TTH_CODING_DRY_RUN", "1") == "1",
        )
    )
