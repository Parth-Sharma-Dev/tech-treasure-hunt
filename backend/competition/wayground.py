"""Original export custody, explicit team mapping and reproducible platform points."""

import base64
import binascii
import hashlib
from decimal import Decimal

from django.db import transaction

from .api import ApiProblem
from .models import Team, WaygroundReport
from .participant import round_eligible
from .results import (
    audit_replay,
    locked_round,
    record_action,
    require_result_role,
    validate_request,
)
from .wayground_workbook import MAX_BYTES, read_workbook

VERSION = "round2-wayground-v2"
STORAGE_BOUND = "9999999.999"


def schema(question_count):
    return {
        "version": VERSION,
        "max_score": STORAGE_BOUND,
        "maximum_is_storage_bound": True,
        "question_count": question_count,
        "score_metric": "wayground_score",
        "time_metric": "reported_answer_duration",
        "source_sheet": "Participant Data",
    }


def is_wayground(round, rules=None):
    rules = rules if rules is not None else round.rules_snapshot.get("rules", round.rules)
    return round.number == 2 and rules.get("score_schema", {}).get("version") == VERSION


def report_data(report):
    try:
        raw = base64.b64decode(report.content_base64, validate=True)
        if hashlib.sha256(raw).hexdigest() != report.sha256:
            raise ValueError("Original workbook checksum differs.")
        metadata, participants = read_workbook(raw)
        if metadata != report.metadata or participants != report.participants:
            raise ValueError("Retained workbook values differ from the original file.")
        return metadata, participants
    except (ValueError, binascii.Error) as error:
        raise ApiProblem("invalid_report", str(error), 409) from None


@transaction.atomic
def upload_report(round_id, actor, data):
    require_result_role(actor)
    action_id, reason = validate_request(data)
    round = locked_round(round_id)
    if not is_wayground(round) or round.state not in ["ENDED", "PROVISIONAL"]:
        raise ApiProblem(
            "invalid_transition", "Use an ended Wayground Round 2 before importing its report.", 409
        )
    encoded, filename = data.get("content_base64"), data.get("filename")
    if not isinstance(encoded, str) or len(encoded) > 1_333_340 or not isinstance(filename, str):
        raise ApiProblem("invalid_report", "Supply a bounded original .xlsx workbook.")
    filename = filename.replace("\\", "/").rsplit("/", 1)[-1]
    if not filename.lower().endswith(".xlsx") or len(filename) > 200:
        raise ApiProblem("invalid_report", "Choose the original .xlsx export.")
    try:
        raw = base64.b64decode(encoded, validate=True)
        if len(raw) > MAX_BYTES:
            raise ValueError("The workbook exceeds 1 MB.")
        metadata, participants = read_workbook(raw)
    except (ValueError, binascii.Error) as error:
        raise ApiProblem("invalid_report", str(error)) from None
    checksum = hashlib.sha256(raw).hexdigest()
    fingerprint = {
        "round_id": round_id,
        "actor_id": actor.pk,
        "sha256": checksum,
        "filename": filename,
        "reason": reason,
        "kind": "wayground_upload",
    }
    if replay := audit_replay(action_id, fingerprint):
        return replay
    if (
        metadata["question_count"]
        != round.rules_snapshot["rules"]["score_schema"]["question_count"]
    ):
        raise ApiProblem(
            "invalid_report", "Report question count differs from the frozen quiz settings."
        )
    report, _ = WaygroundReport.objects.get_or_create(
        round=round,
        sha256=checksum,
        defaults={
            "maker": actor,
            "filename": filename,
            "content_base64": encoded,
            "metadata": metadata,
            "participants": participants,
        },
    )
    response = {
        "report_id": report.pk,
        "sha256": checksum,
        "metadata": metadata,
        "participants": participants,
    }
    record_action(action_id, actor, "upload_wayground", reason, fingerprint, response)
    return response


def validate_mapping(round, rows, enforce_eligibility=True):
    required = {"report_id", "source_row", "team_code", "excluded", "exclusion_reason"}
    if not rows or any(not isinstance(row, dict) or set(row) != required for row in rows):
        return [], [
            {"message": "Map every report participant or explicitly exclude them with a reason."}
        ]
    ids = {row["report_id"] for row in rows if type(row["report_id"]) is int}
    if len(ids) != 1 or any(type(row["report_id"]) is not int for row in rows):
        return [], [{"message": "Use exactly one original report per source batch."}]
    report = WaygroundReport.objects.filter(pk=next(iter(ids)), round=round).first()
    if not report:
        return [], [{"message": "Original report does not belong to this Round 2."}]
    try:
        metadata, participants = report_data(report)
    except ApiProblem as error:
        return [], [{"message": str(error)}]
    if (
        metadata["question_count"]
        != round.rules_snapshot["rules"]["score_schema"]["question_count"]
    ):
        return [], [{"message": "Quiz question count differs from the frozen report schema."}]
    sources = {row["source_row"]: row for row in participants}
    teams = {t.code: t for t in Team.objects.filter(is_demo=round.is_demo)}
    preview, errors, seen, assigned = [], [], set(), set()
    for index, row in enumerate(rows, 1):
        try:
            source_id = row["source_row"]
            if type(source_id) is not int or source_id not in sources or source_id in seen:
                raise ValueError("Map each original participant row exactly once.")
            seen.add(source_id)
            if type(row["excluded"]) is not bool or not isinstance(row["exclusion_reason"], str):
                raise ValueError("Use an explicit exclusion decision and reason.")
            if row["excluded"]:
                if (
                    row["team_code"]
                    or not row["exclusion_reason"].strip()
                    or len(row["exclusion_reason"]) > 200
                ):
                    raise ValueError("Excluded players require no team and a retained reason.")
                continue
            code = row["team_code"]
            team = teams.get(code) if isinstance(code, str) else None
            if not team or enforce_eligibility and not round_eligible(team, round):
                raise ValueError("Map to an active finally qualified team in this cohort.")
            if code in assigned or row["exclusion_reason"]:
                raise ValueError(
                    "A team can have only one included player/attempt in a report batch."
                )
            assigned.add(code)
            source = sources[source_id]
            if source["counts"]["Yet to be graded"]:
                raise ValueError("Wait for final Wayground grading and export a corrected report.")
            if source["answer_time_ms"] > round.active_budget_ms:
                raise ValueError("Reported answering duration exceeds the approved quiz budget.")
            preview.append(
                {
                    "team_code": code,
                    "score": str(Decimal(source["score"])),
                    "max_score": STORAGE_BOUND,
                    "tie_metrics": {
                        "reported_answer_time_ms": source["answer_time_ms"],
                        "report_id": report.pk,
                        "source_row": source_id,
                        "player_name": source["player_name"],
                        "raw_platform_score": source["score"],
                        "question_count": metadata["question_count"],
                    },
                    "source_reference": f"Wayground {report.sha256}: row {source_id}",
                }
            )
        except (ValueError, TypeError) as error:
            errors.append({"row": index, "message": str(error)})
    if seen != set(sources):
        errors.append(
            {"message": "Every original player needs a mapping or an explicit reviewed exclusion."}
        )
    return sorted(preview, key=lambda r: r["team_code"]), errors
