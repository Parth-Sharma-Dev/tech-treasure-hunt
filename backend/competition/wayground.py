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
    if rows and any(isinstance(row, dict) and row.get("absent") is True for row in rows):
        return validate_absences(round, rows, enforce_eligibility)
    required = {"report_id", "source_row", "team_code", "excluded", "exclusion_reason"}
    workbook_ranking = any(
        isinstance(row, dict) and row.get("use_workbook_rank") is True for row in rows
    )
    if workbook_ranking:
        required |= {"use_workbook_rank", "ranking_change_reference"}
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
        if workbook_ranking:
            _, participants = read_workbook(
                base64.b64decode(report.content_base64, validate=True), include_ranking=True
            )
    except (ApiProblem, ValueError) as error:
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
            if workbook_ranking and (
                row["use_workbook_rank"] is not True
                or not isinstance(row["ranking_change_reference"], str)
                or not row["ranking_change_reference"].strip()
                or len(row["ranking_change_reference"]) > 200
            ):
                raise ValueError(
                    "Confirm workbook ranking and supply its reviewed decision reference."
                )
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
            if workbook_ranking:
                preview[-1]["tie_metrics"].update(
                    workbook_rank=source["workbook_rank"],
                    reported_accuracy=source["reported_accuracy"],
                    ranking_change_reference=row["ranking_change_reference"],
                )
        except (ValueError, TypeError) as error:
            errors.append({"row": index, "message": str(error)})
    if seen != set(sources):
        errors.append(
            {"message": "Every original player needs a mapping or an explicit reviewed exclusion."}
        )
    return sorted(preview, key=lambda r: r["team_code"]), errors


def validate_absences(round, rows, enforce_eligibility=True):
    """Attendance evidence is separate from the immutable platform workbook."""
    from .external_scores import current_scores

    required = {"team_code", "absent", "absence_reason", "attendance_reference"}
    teams = {t.code: t for t in Team.objects.filter(is_demo=round.is_demo)}
    scores = current_scores(round)
    preview, errors, seen = [], [], set()
    for index, row in enumerate(rows, 1):
        try:
            if not isinstance(row, dict) or set(row) != required or row["absent"] is not True:
                raise ValueError("Use a separate batch of explicit absence evidence only.")
            code = row["team_code"]
            if not isinstance(code, str) or code in seen:
                raise ValueError("Supply each absent team exactly once.")
            seen.add(code)
            team = teams.get(code)
            if not team or enforce_eligibility and not round_eligible(team, round):
                raise ValueError("Absence must concern an eligible team in this cohort.")
            for key in ("absence_reason", "attendance_reference"):
                if not isinstance(row[key], str) or not row[key].strip() or len(row[key]) > 200:
                    raise ValueError(
                        "Supply bounded absence reason and attendance evidence reference."
                    )
            existing = scores.get(team.pk)
            if existing and existing.tie_metrics.get("absent") is not True:
                raise ValueError("A recorded participant score cannot be replaced by an absence.")
            preview.append(
                {
                    "team_code": code,
                    "score": "0",
                    "max_score": STORAGE_BOUND,
                    "tie_metrics": {
                        "absent": True,
                        "absence_reason": row["absence_reason"],
                        "attendance_reference": row["attendance_reference"],
                    },
                    "source_reference": row["attendance_reference"],
                }
            )
        except (ValueError, TypeError) as error:
            errors.append({"row": index, "message": str(error)})
    return sorted(preview, key=lambda r: r["team_code"]), errors
