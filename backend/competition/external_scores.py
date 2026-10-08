"""Versioned external score intake. Source rows remain private and never execute."""

import csv
import io
import re
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

from django.db import transaction

from .api import ApiProblem
from .clock import database_now
from .models import ImportBatch, Round, ScoreRevision, Team
from .participant import round_eligible
from .results import (
    audit_replay,
    digest,
    locked_round,
    record_action,
    require_result_role,
    validate_request,
)
from .rules import require_staff_permission

CRITERIA = {
    "technical": Decimal(4),
    "problem_solving": Decimal("2.5"),
    "communication": Decimal(2),
    "coordination": Decimal("1.5"),
}
HEADERS = {
    2: ["team_code", "correct_question_ids", "official_finish_active_ms", "source_reference"],
    4: ["team_code", "faculty_id", *CRITERIA, "source_reference"],
}


def decimal_value(value, maximum):
    if isinstance(value, bool) or not isinstance(value, (str, int, float, Decimal)):
        raise ValueError("Marks must be finite numbers with at most three decimal places.")
    try:
        number = Decimal(str(value))
        if (
            not number.is_finite()
            or number < 0
            or number > maximum
            or number.as_tuple().exponent < -3
        ):
            raise ValueError("Marks are out of range or exceed three decimal places.")
        return number
    except InvalidOperation:
        raise ValueError("Marks must be finite numbers.") from None


def schema_errors(round, rules=None):
    frozen = rules is not None
    rules = rules if rules is not None else round.rules
    schema = rules.get("score_schema", {})
    expected = f"round{round.number}-v1"
    errors = []
    if not isinstance(schema, dict) or schema.get("version") != expected:
        return [f"Configure score_schema.version as {expected}."]
    try:
        maximum = decimal_value(schema.get("max_score"), Decimal("9999999.999"))
        if maximum <= 0:
            raise ValueError()
    except ValueError:
        errors.append("Set a positive maximum score in the approved schema.")
    if rules.get("ranking_policy") != (
        "score_then_finish_time" if round.number == 2 else "weighted_faculty_criteria"
    ):
        errors.append("Configure the supported external ranking policy.")
    if rules.get("qualification_tie_policy") not in [
        "block_exact_ties",
        "supervised_reserve_question",
        "supervised_reserve_clue",
    ]:
        errors.append("Choose an explicit supported tie policy.")
    if round.number == 2:
        ids = schema.get("question_ids")
        if (
            not isinstance(ids, list)
            or not ids
            or len(ids) > 30
            or any(
                not isinstance(value, str) or re.fullmatch(r"[A-Za-z0-9_-]{1,40}", value) is None
                for value in ids
            )
            or len(set(ids)) != len(ids)
            or str(schema.get("max_score")) != str(len(ids))
        ):
            errors.append("Round 2 needs unique question IDs and maximum equal to their count.")
        if not round.is_demo and (
            round.advancement_count != 15
            or not isinstance(ids, list)
            or len(ids) != 30
            or round.active_budget_ms != 2_700_000
        ):
            errors.append("Real Round 2 requires 30 questions, 45 minutes and 15 qualifiers.")
    if round.number == 4:
        if schema.get("max_score") != "100" or schema.get("rounding") != "half_up_3":
            errors.append("Round 4 requires maximum 100 and half_up_3 rounding.")
        panels = rules.get("faculty_panels")
        if not isinstance(panels, list) or not panels:
            errors.append("Configure faculty panels and team interview slots.")
        else:
            from .faculty import panel_errors

            errors += panel_errors(round, panels, frozen=frozen)
        if not round.is_demo and round.advancement_count != 5:
            errors.append("Round 4 awards five Green Cards.")
    return errors


def require_external(round):
    if round.number not in HEADERS or round.delivery_mode != Round.Delivery.EXTERNAL:
        raise ApiProblem("unsupported_round", "External score intake supports Round 2 and Round 4.")
    errors = schema_errors(round, round.rules_snapshot.get("rules", {}))
    if errors:
        raise ApiProblem("invalid_schema", " ".join(errors), 409)


def current_scores(round):
    return {item.team_id: item for item in ScoreRevision.objects.filter(round=round).order_by("pk")}


def voided_questions(round):
    from .models import ExternalQuestionVoid

    return set(
        ExternalQuestionVoid.objects.filter(proposal__round=round).values_list(
            "proposal__question_id", flat=True
        )
    )


def effective_question_score(round, metrics):
    question_ids = set(round.rules_snapshot["rules"]["score_schema"]["question_ids"])
    voids = voided_questions(round)
    correct = metrics.get("correct_question_ids")
    if (
        not isinstance(correct, list)
        or any(not isinstance(value, str) for value in correct)
        or len(set(correct)) != len(correct)
        or not set(correct) <= question_ids
    ):
        raise ValueError("Question credit evidence is malformed.")
    return Decimal(len(set(correct) - voids)), Decimal(len(question_ids - voids))


def intake_digest(round):
    from .models import Incident, ResultSnapshot

    previous = (
        Round.objects.filter(number=round.number - 1, is_demo=round.is_demo)
        .order_by("-attempt_no")
        .first()
    )
    return digest(
        {
            "rules": round.rules_digest,
            "version": round.control_version,
            "previous_final": list(
                ResultSnapshot.objects.filter(round=previous).order_by("-revision")[:1].values()
            ),
            "incidents": list(
                Incident.objects.filter(round__in=[value for value in [round, previous] if value])
                .order_by("pk")
                .values()
            ),
            "teams": list(Team.objects.filter(is_demo=round.is_demo).order_by("pk").values()),
            "scores": list(ScoreRevision.objects.filter(round=round).order_by("pk").values()),
            "voids": sorted(voided_questions(round)),
            "eligible": [
                team.pk
                for team in Team.objects.filter(is_demo=round.is_demo).order_by("pk")
                if round_eligible(team, round)
            ],
        }
    )


def parse_rows(round, data):
    if "csv" in data:
        content = data["csv"]
        if not isinstance(content, str) or len(content.encode("utf-8")) > 1_000_000:
            raise ApiProblem("invalid_input", "Supply UTF-8 CSV of at most 1 MB.")
        try:
            reader = csv.DictReader(io.StringIO(content.lstrip("\ufeff")), strict=True)
            if reader.fieldnames != HEADERS[round.number]:
                raise ApiProblem(
                    "invalid_headers", "Required columns: " + ",".join(HEADERS[round.number])
                )
            rows = list(reader)
        except csv.Error:
            raise ApiProblem("invalid_csv", "The CSV is malformed.") from None
    else:
        rows = data.get("rows")
    if not isinstance(rows, list) or not 1 <= len(rows) <= 2000:
        raise ApiProblem("invalid_input", "Supply 1–2000 source rows.")
    if any(
        not isinstance(row, dict) or any(not isinstance(key, str) for key in row) for row in rows
    ):
        raise ApiProblem("invalid_input", "Source rows must be objects; check for extra CSV cells.")
    return rows


def validate_rows(round, rows, enforce_eligibility=True):
    maximum = Decimal(round.rules_snapshot["rules"]["score_schema"]["max_score"])
    teams = {item.code: item for item in Team.objects.filter(is_demo=round.is_demo)}
    groups, errors, seen = {}, [], set()
    panels = round.rules_snapshot["rules"].get("faculty_panels", [])
    assignments = {slot["team_code"]: panel for panel in panels for slot in panel["slots"]}
    for index, row in enumerate(rows, 1):
        try:
            if not isinstance(row, dict) or set(row) != set(HEADERS[round.number]):
                raise ValueError("Every row must contain exactly the schema columns.")
            code = row["team_code"]
            team = teams.get(code) if isinstance(code, str) else None
            if team is None or (enforce_eligibility and not round_eligible(team, round)):
                raise ValueError("Team is unknown, inactive or not qualified for this attempt.")
            ref = row["source_reference"]
            if not isinstance(ref, str) or not ref.strip() or len(ref) > 200:
                raise ValueError(
                    "A source evidence reference of at most 200 characters is required."
                )
            if round.number == 2:
                key = code
                correct = row["correct_question_ids"]
                if isinstance(correct, str):
                    correct = correct.split("|") if correct else []
                allowed = round.rules_snapshot["rules"]["score_schema"]["question_ids"]
                if (
                    not isinstance(correct, list)
                    or any(not isinstance(value, str) for value in correct)
                    or len(set(correct)) != len(correct)
                    or not set(correct) <= set(allowed)
                ):
                    raise ValueError(
                        "Correct IDs must be unique released question IDs; separate CSV IDs with |."
                    )
                score = Decimal(len(correct))
                finish = str(row["official_finish_active_ms"])
                if not re.fullmatch(r"[0-9]{1,12}", finish) or int(finish) > round.active_budget_ms:
                    raise ValueError(
                        "Finish time must be integer active milliseconds within the budget."
                    )
                normalized = {
                    "team_code": code,
                    "score": str(score),
                    "max_score": str(maximum),
                    "tie_metrics": {
                        "official_finish_active_ms": int(finish),
                        "correct_question_ids": sorted(correct),
                    },
                    "source_reference": ref,
                }
            else:
                faculty = str(row["faculty_id"])
                if not re.fullmatch(r"[1-9][0-9]*", faculty):
                    raise ValueError("Faculty ID must be a positive integer.")
                faculty = int(faculty)
                panel = assignments.get(code)
                if panel is None or faculty not in panel["faculty_ids"]:
                    raise ValueError("Faculty must belong to this team's frozen panel assignment.")
                key = (code, faculty)
                normalized = {
                    "faculty_id": faculty,
                    "marks": {
                        field: str(decimal_value(row[field], Decimal(10))) for field in CRITERIA
                    },
                    "source_reference": ref,
                }
            if key in seen:
                raise ValueError("Duplicate team or team/faculty source row.")
            seen.add(key)
            groups.setdefault(code, []).append(normalized)
        except (ValueError, TypeError) as exc:
            errors.append({"row": index, "message": str(exc)})
    preview = []
    for code, marks in groups.items():
        if round.number == 2:
            preview.append(marks[0])
        else:
            if {item["faculty_id"] for item in marks} != set(assignments[code]["faculty_ids"]):
                errors.append(
                    {
                        "team_code": code,
                        "message": "All three panel faculty marks are required; no inferred marks.",
                    }
                )
                continue
            averages = {
                field: (sum(Decimal(item["marks"][field]) for item in marks) / Decimal(3)).quantize(
                    Decimal("0.001"), rounding=ROUND_HALF_UP
                )
                for field in CRITERIA
            }
            total = sum(averages[field] * weight for field, weight in CRITERIA.items()).quantize(
                Decimal("0.001"), rounding=ROUND_HALF_UP
            )
            preview.append(
                {
                    "team_code": code,
                    "score": str(total),
                    "max_score": "100",
                    "tie_metrics": {
                        "averages": {key: str(value) for key, value in averages.items()},
                        "faculty_marks": sorted(marks, key=lambda item: item["faculty_id"]),
                    },
                    "source_reference": f"Panel {assignments[code]['label']}: faculty source rows"[
                        :200
                    ],
                }
            )
    return preview, errors


@transaction.atomic
def validate_import(round_id, actor, data):
    require_result_role(actor)
    action_id, reason = validate_request(data)
    round = locked_round(round_id)
    fingerprint = {
        **data,
        "kind": "validate_external_import",
        "round_id": round_id,
        "actor_id": actor.pk,
    }
    if replay := audit_replay(action_id, fingerprint):
        return replay
    require_external(round)
    if round.state not in ["ENDED", "PROVISIONAL"]:
        raise ApiProblem("invalid_transition", "End the round before recording scores.", 409)
    if data.get("schema_version") != round.rules_snapshot["rules"]["score_schema"]["version"]:
        raise ApiProblem("invalid_schema", "Supply the frozen score schema version.")
    rows = parse_rows(round, data)
    file_digest = digest({"rows": rows, "schema": data["schema_version"], "reason": reason})
    batch = ImportBatch.objects.filter(round=round, file_digest=file_digest).first()
    if batch is None:
        preview, errors = validate_rows(round, rows)
        batch = ImportBatch.objects.create(
            round=round,
            file_digest=file_digest,
            schema_version=data["schema_version"],
            maker=actor,
            reason=reason,
            source_rows=rows,
            preview=preview,
            dry_run_errors=errors,
            evidence_digest=intake_digest(round),
        )
    response = {
        "batch_id": batch.pk,
        "errors": batch.dry_run_errors,
        "preview": batch.preview,
        "committed": batch.committed_at is not None,
    }
    record_action(action_id, actor, "validate_external_import", reason, fingerprint, response)
    return response


@transaction.atomic
def commit_import(round_id, actor, data):
    require_staff_permission(actor, "verify_evidence")
    action_id, reason = validate_request(data)
    round = locked_round(round_id)
    fingerprint = {
        **data,
        "kind": "review_external_import",
        "round_id": round_id,
        "actor_id": actor.pk,
    }
    if replay := audit_replay(action_id, fingerprint):
        return replay
    batch = (
        ImportBatch.objects.filter(round=round, pk=data.get("batch_id")).first()
        if type(data.get("batch_id")) is int
        else None
    )
    if batch is None:
        raise ApiProblem("not_found", "Score batch not found.", 404)
    if actor.pk == batch.maker_id:
        raise ApiProblem(
            "independent_reviewer", "A different verifier must review source marks.", 403
        )
    require_result_role(batch.maker)
    if batch.committed_at:
        response = {"batch_id": batch.pk, "committed": True}
        record_action(action_id, actor, "review_external_import", reason, fingerprint, response)
        return response
    if AuditEventRejected(batch):
        raise ApiProblem(
            "invalid_transition", "This batch was rejected; prepare a new intake.", 409
        )
    reject = data.get("reject") is True
    if not reject:
        require_external(round)
        if round.state not in ["ENDED", "PROVISIONAL"] or batch.evidence_digest != intake_digest(
            round
        ):
            raise ApiProblem(
                "stale_evidence",
                "Scores, eligibility or rules changed; prepare a fresh preview.",
                409,
            )
        preview, errors = validate_rows(round, batch.source_rows)
        if errors or batch.dry_run_errors or preview != batch.preview:
            raise ApiProblem(
                "invalid_scores", "The entire batch must pass validation before commit.", 409
            )
        if data.get("evidence_confirmed") is not True:
            raise ApiProblem(
                "evidence_required",
                "Confirm independent review of original source marks and finish evidence.",
            )
        previous = current_scores(round)
        teams = {item.code: item for item in Team.objects.filter(is_demo=round.is_demo)}
        for row in preview:
            team = teams[row["team_code"]]
            revision = ScoreRevision(
                round=round,
                team=team,
                score=Decimal(row["score"]),
                max_score=Decimal(row["max_score"]),
                tie_metrics=row["tie_metrics"],
                source_reference=row["source_reference"],
                import_batch=batch,
                reason=batch.reason,
                maker=batch.maker,
                verifier=actor,
                supersedes=previous.get(team.pk),
            )
            revision.full_clean()
            revision.save()
        batch.verifier = actor
        batch.committed_at = database_now()
        batch.save(update_fields=["verifier", "committed_at"])
        round.control_version += 1
        round.save(update_fields=["control_version"])
    response = {"batch_id": batch.pk, "committed": not reject, "rejected": reject}
    record_action(action_id, actor, "review_external_import", reason, fingerprint, response)
    return response


def AuditEventRejected(batch):
    from .models import AuditEvent

    return AuditEvent.objects.filter(
        action="review_external_import",
        after__response__batch_id=batch.pk,
        after__response__rejected=True,
    ).exists()
