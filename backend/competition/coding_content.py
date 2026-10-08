import json
from decimal import Decimal

from .models import CodingTask

CATEGORY_POINTS = {"OUTPUT": 15, "DEBUG": 25, "FILL": 20, "SHORT": 30, "LOGIC": 10}


def task_errors(task):
    errors = []
    if task.round.number != 3 or task.round.delivery_mode != "CODING":
        errors.append("Attach coding tasks to a native CODING Round 3 draft.")
    allowed = (
        ["PYTHON", "C"] if task.category in ["DEBUG", "FILL", "SHORT"] else ["PYTHON", "C", "TEXT"]
    )
    if (
        not isinstance(task.languages, list)
        or not task.languages
        or any(item not in allowed for item in task.languages)
    ):
        errors.append("Choose supported response languages for this task category.")
    if (
        not isinstance(task.private_rubric, dict)
        or not task.private_rubric
        or len(json.dumps(task.private_rubric).encode()) > 65536
    ):
        errors.append("Supply a private lab rubric of at most 64 KiB.")
    if task.category == "SHORT":
        tests = (
            task.private_rubric.get("test_cases", [])
            if isinstance(task.private_rubric, dict)
            else []
        )
        if (
            not isinstance(tests, list)
            or not 1 <= len(tests) <= 256
            or any(
                not isinstance(item, dict)
                or not isinstance(item.get("id"), str)
                or not item["id"]
                or len(item["id"]) > 100
                or "input" not in item
                or "expected" not in item
                for item in tests
            )
        ):
            errors.append("Short coding tasks require fixed id/input/expected hidden tests.")
        elif len({item["id"] for item in tests}) != len(tests):
            errors.append("Hidden test IDs must be unique.")
    return errors


def task_snapshot(task):
    return {
        "id": task.pk,
        "public_id": task.public_id,
        "category": task.category,
        "prompt": task.prompt,
        "starter_code": task.starter_code,
        "languages": task.languages,
        "points": str(task.points),
        "version": task.version,
        "private_rubric": task.private_rubric,
        "prepared_by": task.prepared_by_id,
        "verified_by": task.verified_by_id,
    }


def tasks_snapshot(round):
    return [task_snapshot(item) for item in CodingTask.objects.filter(round=round).order_by("pk")]


def readiness_errors(round):
    tasks = list(CodingTask.objects.filter(round=round).order_by("pk"))
    errors = []
    if not 1 <= len(tasks) <= 100:
        errors.append("Add and verify a bounded coding task set (up to 100 tasks).")
    totals = {key: Decimal(0) for key in CATEGORY_POINTS}
    for task in tasks:
        errors += task_errors(task)
        if task.category in totals:
            totals[task.category] += task.points
        if (
            not task.version
            or not task.prompt
            or not task.verified_at
            or task.prepared_by_id is None
            or task.prepared_by_id == task.verified_by_id
        ):
            errors.append(f"{task.public_id} needs a version and independent content verification.")
        elif (
            not task.prepared_by.is_active
            or not task.verified_by.is_active
            or not task.prepared_by.is_staff
            or not task.verified_by.is_staff
        ):
            errors.append(f"{task.public_id} requires active staff owners.")
    if any(totals[key] != points for key, points in CATEGORY_POINTS.items()):
        errors.append("Category totals must be 15/25/20/30/10, totaling 100 marks.")
    expected = {
        "submission_policy": "locked_final_with_cutoff_autofinalize",
        "ranking_policy": "score_correct_tasks_final_time",
        "qualification_tie_policy": "supervised_reserve_task",
        "one_workstation_per_team": True,
        "score_precision": 3,
    }
    for key, value in expected.items():
        if type(round.rules.get(key)) is not type(value) or round.rules.get(key) != value:
            errors.append(f"Configure the supported Round 3 policy for {key}.")
    versions = round.rules.get("language_versions")
    if (
        not isinstance(versions, dict)
        or set(versions) != {"PYTHON", "C"}
        or any(
            not isinstance(value, str) or not value.strip() or len(value) > 100
            for value in versions.values()
        )
    ):
        errors.append("Record the approved lab Python and C toolchain versions.")
    if not round.is_demo and (round.active_budget_ms != 2700000 or round.advancement_count != 10):
        errors.append("The real Round 3 requires 45 active minutes and top 10 advancement.")
    return errors
