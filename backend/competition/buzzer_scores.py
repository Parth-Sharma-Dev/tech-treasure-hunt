"""Reviewed question ledgers reproduce scores from native press and host evidence."""

import re
from decimal import Decimal, InvalidOperation

from django.db import transaction

from .api import ApiProblem
from .buzzer import admission_fence, native_round, queue
from .buzzer_answers import priority_order
from .buzzer_content import questions_snapshot
from .buzzer_scoring_rules import contract_for, points_for_stage, reveal_stage, schema_errors
from .clock import database_now
from .models import (
    AuditEvent,
    BuzzerAnswerEvidence,
    BuzzerClosure,
    BuzzerPress,
    BuzzerScoreRevision,
    BuzzerWindow,
    ImportBatch,
    Incident,
    Round,
    RoundPhase,
    Team,
)
from .results import (
    audit_replay,
    digest,
    latest_snapshot,
    locked_round,
    record_action,
    require_result_role,
    validate_request,
)
from .rules import require_staff_permission, snapshot_digest

HEADERS = [
    "window_id",
    "team_code",
    "press_id",
    "answer_evidence_id",
    "verdict",
    "answer",
    "reveal_step",
    "buzzer_tie_order",
    "adjudication_reference",
    "source_reference",
]
VERDICTS = {"CORRECT", "WRONG", "NO_ANSWER", "NOT_CALLED", "NO_BUZZ", "VOID"}


def require_schema(round):
    native_round(round.pk)
    errors = schema_errors(round, round.rules_snapshot.get("rules", {}))
    if not round.rules_digest or snapshot_digest(round.rules_snapshot) != round.rules_digest:
        errors.append("The frozen rules digest is inconsistent.")
    if questions_snapshot(round) != round.rules_snapshot.get("buzzer_questions"):
        errors.append("The frozen question set needs reconciliation.")
    if errors:
        raise ApiProblem("invalid_schema", " ".join(errors), 409)


def carry_over(round):
    teams = {item.code: item for item in Team.objects.filter(is_demo=round.is_demo)}
    basis, errors = {}, []
    kinds = {}
    for number in range(1, 5):
        prior = (
            Round.objects.filter(number=number, is_demo=round.is_demo)
            .order_by("-attempt_no")
            .first()
        )
        snapshot = latest_snapshot(prior) if prior else None
        if (
            not prior
            or prior.state != "FINALIZED"
            or not snapshot
            or snapshot.status != "FINAL"
            or Incident.objects.filter(round=prior, material=True, closed_at__isnull=True).exists()
        ):
            errors.append(f"Round {number} needs final, reviewed carry-over results.")
            continue
        basis[number] = {
            "snapshot_id": snapshot.pk,
            "qualifiers": snapshot.qualifier_codes,
            "entries": snapshot.ranked_entries,
        }
        kinds[number] = snapshot.metadata.get("ranking_kind")
    codes = basis.get(4, {}).get("qualifiers", [])
    totals = {}
    for code in codes:
        parts, maxima = {}, {}
        if code not in teams:
            errors.append("A finalist is missing from the same-cohort roster.")
            continue
        for number, item in basis.items():
            matches = [entry for entry in item["entries"] if entry.get("team_code") == code]
            try:
                if (
                    len(matches) != 1
                    or matches[0].get("eligible") is not True
                    or code not in item["qualifiers"]
                ):
                    raise ValueError()
                if number == 4 and (
                    contract_for(round)["version"] == "round5-v2" or kinds.get(4) == "GREEN_CARDS"
                ):
                    if kinds.get(4) == "GREEN_CARDS" and (
                        matches[0].get("green_card") is not True
                        or matches[0].get("score") != 0
                        or matches[0].get("max_score") != 0
                    ):
                        raise ValueError()
                    parts[str(number)], maxima[str(number)] = "0", "0"
                    continue
                points, maximum = (
                    Decimal(str(matches[0]["score"])),
                    Decimal(str(matches[0]["max_score"])),
                )
                if (
                    not points.is_finite()
                    or not maximum.is_finite()
                    or not 0 <= points <= maximum
                    or maximum <= 0
                ):
                    raise ValueError()
                parts[str(number)], maxima[str(number)] = str(points), str(maximum)
            except (ValueError, InvalidOperation, KeyError, TypeError):
                errors.append(f"{code} has missing or inconsistent Round {number} final points.")
        if len(parts) == 4:
            totals[code] = {
                "parts": parts,
                "score": sum(map(Decimal, parts.values())),
                "maximum": sum(map(Decimal, maxima.values())),
                "maximum_is_storage_bound": kinds.get(2) == "WAYGROUND_RAW",
            }
    return codes, totals, basis, list(dict.fromkeys(errors))


def current_ledgers(round):
    return {
        item.window_id: item
        for item in BuzzerScoreRevision.objects.filter(window__round=round).order_by("pk")
    }


def source_digest(round):
    _, _, basis, _ = carry_over(round)
    return digest(
        {
            "rules": round.rules_digest,
            "version": round.control_version,
            "carry": basis,
            "teams": list(Team.objects.filter(is_demo=round.is_demo).order_by("pk").values()),
            "windows": list(BuzzerWindow.objects.filter(round=round).order_by("pk").values()),
            "closures": list(
                BuzzerClosure.objects.filter(window__round=round).order_by("pk").values()
            ),
            "presses": list(
                BuzzerPress.objects.filter(window__round=round).order_by("pk").values()
            ),
            "answers": list(
                BuzzerAnswerEvidence.objects.filter(window__round=round).order_by("pk").values()
            ),
            "ledgers": list(
                BuzzerScoreRevision.objects.filter(window__round=round).order_by("pk").values()
            ),
            "incidents": list(Incident.objects.filter(round=round).order_by("pk").values()),
        }
    )


def positive_id(value, optional=False):
    if optional and value in ["", None]:
        return None
    if not re.fullmatch(r"[1-9][0-9]{0,18}", str(value)):
        raise ValueError("Use a positive native database ID.")
    return int(value)


def validate_rows(round, rows):
    codes, _, _, carry_errors = carry_over(round)
    errors = [{"message": message} for message in carry_errors]
    windows = {
        item.pk: item
        for item in BuzzerWindow.objects.filter(round=round).select_related("question")
    }
    groups, seen = {}, set()
    for number, row in enumerate(rows, 1):
        try:
            if set(row) != set(HEADERS):
                raise ValueError(
                    "Use exactly the Round 5 source columns; timestamps/points cannot be imported."
                )
            window_id, code = positive_id(row["window_id"]), row["team_code"]
            window = windows.get(window_id)
            if window is None or not BuzzerClosure.objects.filter(window=window).exists():
                raise ValueError("Use a closed native window in this attempt.")
            if code not in codes or (window_id, code) in seen:
                raise ValueError("Unknown/unqualified team or duplicate team/window row.")
            if row["verdict"] not in VERDICTS:
                raise ValueError("Choose CORRECT, WRONG, NO_ANSWER, NOT_CALLED, NO_BUZZ or VOID.")
            if any(
                not isinstance(row[field], str)
                for field in [
                    "answer",
                    "source_reference",
                    "adjudication_reference",
                    "buzzer_tie_order",
                    "press_id",
                ]
            ):
                raise ValueError("Answer, receipt and private evidence fields must be text.")
            if (
                not row["source_reference"].strip()
                or len(row["source_reference"]) > 200
                or len(row["adjudication_reference"]) > 200
                or len(row["answer"]) > 2000
            ):
                raise ValueError("Supply bounded original answer and private source references.")
            reveal = str(row["reveal_step"] or "0")
            if (
                not re.fullmatch(r"[0-9]{1,3}", reveal)
                or int(reveal) > 100
                or window.question.stage != reveal_stage(round)
                and int(reveal)
            ):
                raise ValueError(
                    "Reveal steps belong only to the progressive image stage; "
                    "they do not change marks."
                )
            entries, _ = queue(window)
            own = next((item for item in entries if item["team_code"] == code), None)
            if row["press_id"] != (own["id"] if own else ""):
                raise ValueError(
                    "Reference the team's earliest native receipt, or blank when it did not buzz."
                )
            note_id = positive_id(row["answer_evidence_id"], optional=True)
            note = (
                BuzzerAnswerEvidence.objects.filter(
                    pk=note_id, window=window, team__code=code
                ).first()
                if note_id
                else None
            )
            if note_id and note is None:
                raise ValueError(
                    "Host-answer evidence belongs to a different team/window or is missing."
                )
            attempted = row["verdict"] in ["CORRECT", "WRONG", "NO_ANSWER"]
            if attempted:
                if (
                    not own
                    or not note
                    or str(note.press_id) != own["id"]
                    or row["answer"] != note.answer
                ):
                    raise ValueError(
                        "Attempted answers need native host evidence and original answer text."
                    )
                if note.verdict != row["verdict"] and not row["adjudication_reference"].strip():
                    raise ValueError(
                        "Changed host verdicts need retained correction/adjudication evidence."
                    )
                if row["verdict"] == "CORRECT" and not note.answer.strip():
                    raise ValueError(
                        "A no-answer record cannot become a fabricated correct answer."
                    )
                phase_covered = any(
                    phase.started_at <= note.completed_at <= phase.ended_at
                    for phase in RoundPhase.objects.filter(round=round, phase_type="LIVE")
                )
                if note.completed_at < note.press.received_at or not phase_covered:
                    raise ValueError("The host completion time needs official live clock evidence.")
            elif row["verdict"] == "NO_BUZZ" and (own or note):
                raise ValueError("NO_BUZZ contradicts a retained native press.")
            elif row["verdict"] == "NOT_CALLED" and not own:
                raise ValueError("Use NO_BUZZ for a team without a receipt.")
            elif note and not row["adjudication_reference"].strip():
                raise ValueError(
                    "Suppressing an original answer requires reviewed adjudication evidence."
                )
            if row["verdict"] == "VOID" and not row["adjudication_reference"].strip():
                raise ValueError("Global voids need private adjudication evidence for every team.")
            normalized = {
                **row,
                "window_id": window_id,
                "answer_evidence_id": note_id,
                "reveal_step": int(reveal),
                "points": points_for_stage(round, window.question.stage)
                if row["verdict"] == "CORRECT"
                else 0,
                "completed_at": note.completed_at.isoformat(timespec="microseconds")
                if note
                else None,
            }
            seen.add((window_id, code))
            groups.setdefault(window_id, []).append(normalized)
        except (ValueError, TypeError, KeyError) as error:
            errors.append({"row": number, "message": str(error)})
    preview = []
    for window_id, items in groups.items():
        try:
            window = windows[window_id]
            if {item["team_code"] for item in items} != set(codes):
                raise ValueError(
                    "Supply an explicit row for every Round 4 finalist in each included window."
                )
            all_void = all(item["verdict"] == "VOID" for item in items)
            if any(item["verdict"] == "VOID" for item in items) and not all_void:
                raise ValueError("A question void applies equally to all finalists.")
            if not all_void:
                tie_fields = {
                    (
                        item["buzzer_tie_order"],
                        item["adjudication_reference"] if item["buzzer_tie_order"] else "",
                    )
                    for item in items
                }
                if len(tie_fields) != 1:
                    raise ValueError("All rows must retain the same adjudicated buzzer order.")
                order_text, tie_reference = next(iter(tie_fields))
                order, _ = priority_order(
                    window, order_text.split("|") if order_text else None, tie_reference
                )
                by_team = {item["team_code"]: item for item in items}
                solved, stopped = False, False
                for code in order:
                    verdict = by_team[code]["verdict"]
                    if solved or stopped:
                        if verdict != "NOT_CALLED":
                            raise ValueError(
                                "No later credit follows a correct answer or uncalled queue gap."
                            )
                    elif verdict == "CORRECT":
                        solved = True
                    elif verdict == "NOT_CALLED":
                        stopped = True
                    elif verdict not in ["WRONG", "NO_ANSWER"]:
                        raise ValueError("Pass only through earlier wrong/no-answer native buzzes.")
                for item in items:
                    if item["answer_evidence_id"]:
                        note = BuzzerAnswerEvidence.objects.get(pk=item["answer_evidence_id"])
                        if (
                            note.priority_evidence.get("order") != order
                            and not item["adjudication_reference"].strip()
                        ):
                            raise ValueError(
                                "Changed priority needs evidence; timestamps stay immutable."
                            )
            preview.append(
                {
                    "window_id": window_id,
                    "question_id": window.question_id,
                    "question_version": window.question.version,
                    "stage": window.question.stage,
                    "void": all_void,
                    "rows": sorted(items, key=lambda item: item["team_code"]),
                }
            )
        except ValueError as error:
            errors.append({"window_id": window_id, "message": str(error)})
    projected = {key: item.payload for key, item in current_ledgers(round).items()}
    projected.update({item["window_id"]: item for item in preview})
    scored_questions = [item["question_id"] for item in projected.values() if not item["void"]]
    if len(set(scored_questions)) != len(scored_questions):
        errors.append(
            {"message": "Void superseded windows through review; never count a question twice."}
        )
    return sorted(preview, key=lambda item: item["window_id"]), errors


def rejected(batch):
    return AuditEvent.objects.filter(
        action="review_buzzer_scores",
        after__response__batch_id=batch.pk,
        after__response__rejected=True,
    ).exists()


def source_context(round):
    codes, _, _, gaps = carry_over(round)
    draft = []
    for window in (
        BuzzerWindow.objects.filter(round=round).select_related("question").order_by("pk")
    ):
        entries, _ = queue(window)
        notes = {
            item.team.code: item
            for item in BuzzerAnswerEvidence.objects.filter(window=window).select_related("team")
        }
        retained_priority = next(iter(notes.values())).priority_evidence if notes else {}
        for code in codes:
            own = next((item for item in entries if item["team_code"] == code), None)
            note = notes.get(code)
            order = retained_priority.get("order", [])
            tied = len({item["received_at"] for item in entries}) != len(entries)
            draft.append(
                {
                    "window_id": str(window.pk),
                    "team_code": code,
                    "press_id": own["id"] if own else "",
                    "answer_evidence_id": str(note.pk) if note else "",
                    "verdict": note.verdict if note else "",
                    "answer": note.answer if note else "",
                    "reveal_step": "0",
                    "buzzer_tie_order": "|".join(order) if tied and order else "",
                    "adjudication_reference": retained_priority.get("adjudication_reference", ""),
                    "source_reference": note.source_reference if note else "",
                }
            )
    return {"draft_source_rows": draft, "carry_over_gaps": gaps}


@transaction.atomic
def validate_import(round_id, actor, data):
    require_result_role(actor)
    action_id, reason = validate_request(data)
    native_round(round_id)
    admission_fence(round_id)
    round = locked_round(round_id)
    fingerprint = {
        **data,
        "kind": "validate_buzzer_scores",
        "round_id": round_id,
        "actor_id": actor.pk,
    }
    if replay := audit_replay(action_id, fingerprint):
        return replay
    require_schema(round)
    if round.state not in ["ENDED", "PROVISIONAL"]:
        raise ApiProblem("invalid_transition", "End Round 5 before reviewing score sources.", 409)
    schema_version = contract_for(round)["version"]
    if data.get("schema_version") != schema_version:
        raise ApiProblem("invalid_schema", f"Use the frozen {schema_version} source contract.")
    from .external_scores import parse_rows

    rows = parse_rows(round, data)
    stamp = digest({"rows": rows, "schema": schema_version, "reason": reason})
    batch = ImportBatch.objects.filter(round=round, file_digest=stamp).first()
    if batch is None:
        preview, errors = validate_rows(round, rows)
        batch = ImportBatch.objects.create(
            round=round,
            maker=actor,
            reason=reason,
            schema_version=schema_version,
            file_digest=stamp,
            source_rows=rows,
            preview=preview,
            dry_run_errors=errors,
            evidence_digest=source_digest(round),
        )
    response = {
        "batch_id": batch.pk,
        "preview": batch.preview,
        "errors": batch.dry_run_errors,
        "committed": batch.committed_at is not None,
    }
    record_action(action_id, actor, "validate_buzzer_scores", reason, fingerprint, response)
    return response


@transaction.atomic
def commit_import(round_id, actor, data):
    require_staff_permission(actor, "verify_evidence")
    action_id, reason = validate_request(data)
    native_round(round_id)
    admission_fence(round_id)
    round = locked_round(round_id)
    fingerprint = {
        **data,
        "kind": "review_buzzer_scores",
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
        raise ApiProblem("not_found", "Source batch not found.", 404)
    if batch.maker_id == actor.pk:
        raise ApiProblem(
            "independent_reviewer",
            "A different verifier must check the buzzer-linked source rows.",
            403,
        )
    require_result_role(batch.maker)
    if batch.committed_at:
        return {"batch_id": batch.pk, "committed": True}
    if rejected(batch):
        raise ApiProblem("invalid_transition", "This source batch was rejected.", 409)
    reject = data.get("reject") is True
    if not reject:
        require_schema(round)
        if round.state not in ["ENDED", "PROVISIONAL"] or batch.evidence_digest != source_digest(
            round
        ):
            raise ApiProblem(
                "stale_evidence",
                "Native evidence, carry-over or scores changed; prepare a fresh preview.",
                409,
            )
        preview, errors = validate_rows(round, batch.source_rows)
        if errors or batch.dry_run_errors or preview != batch.preview:
            raise ApiProblem(
                "invalid_scores", "All source rows must reproduce the reviewed preview.", 409
            )
        if data.get("evidence_confirmed") is not True:
            raise ApiProblem(
                "evidence_required",
                "Confirm review of receipts, offline answers, completion times and carry-over.",
            )
        previous = current_ledgers(round)
        for item in preview:
            BuzzerScoreRevision.objects.create(
                window_id=item["window_id"],
                import_batch=batch,
                payload=item,
                evidence_digest=digest(item),
                maker=batch.maker,
                verifier=actor,
                supersedes=previous.get(item["window_id"]),
            )
        batch.verifier, batch.committed_at = actor, database_now()
        batch.save(update_fields=["verifier", "committed_at"])
        round.control_version += 1
        round.save(update_fields=["control_version"])
    response = {"batch_id": batch.pk, "committed": not reject, "rejected": reject}
    record_action(action_id, actor, "review_buzzer_scores", reason, fingerprint, response)
    return response
