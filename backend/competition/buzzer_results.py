"""One cumulative event winner; no Round 6 advancement is created."""

from decimal import Decimal

from .api import ApiProblem
from .buzzer_scores import (
    HEADERS,
    carry_over,
    current_ledgers,
    rejected,
    require_schema,
    source_digest,
    validate_rows,
)
from .buzzer_scoring_rules import points_for_stage
from .clock import milliseconds
from .models import BuzzerClosure, BuzzerWindow, ImportBatch, Incident, RoundPhase, Team
from .participant import round_eligible
from .results import digest, latest_snapshot


def build_preview(round, now):
    configuration, gaps = [], []
    try:
        require_schema(round)
    except ApiProblem as error:
        configuration.append(str(error))
    codes, carried, basis, carry_gaps = carry_over(round)
    gaps += carry_gaps
    phases = list(RoundPhase.objects.filter(round=round).order_by("started_at", "pk"))
    if (
        round.state not in ["ENDED", "PROVISIONAL", "FINALIZED"]
        or round.live_started_at
        or round.phase_started_at
        or round.deadline_at
    ):
        gaps.append("End and persist Round 5 before publishing winners.")
    if (
        not phases
        or not any(phase.phase_type == "LIVE" for phase in phases)
        or sum(
            milliseconds(phase.ended_at - phase.started_at)
            for phase in phases
            if phase.phase_type == "LIVE"
        )
        != round.accumulated_active_ms
        or any(
            left.ended_at != right.started_at
            for left, right in zip(phases, phases[1:], strict=False)
        )
    ):
        gaps.append("Round 5 clock intervals need reconciliation.")
    windows = list(BuzzerWindow.objects.filter(round=round).order_by("pk"))
    ledgers = current_ledgers(round)
    if any(not BuzzerClosure.objects.filter(window=window).exists() for window in windows):
        gaps.append("Close every native buzzer window before publication.")
    if set(ledgers) != {window.pk for window in windows}:
        gaps.append("Every retained native window needs a reviewed score/void ledger.")
    questions = round.rules_snapshot.get("buzzer_questions", [])
    if {window.question_id for window in windows} != {item["id"] for item in questions}:
        gaps.append("All 25 frozen questions need retained play/void coverage.")
    if ledgers and not configuration:
        source_rows = [
            {field: row[field] for field in HEADERS}
            for ledger in ledgers.values()
            for row in ledger.payload["rows"]
        ]
        reproduced, errors = validate_rows(round, source_rows)
        if errors or reproduced != sorted(
            [item.payload for item in ledgers.values()], key=lambda item: item["window_id"]
        ):
            gaps.append("Current question ledgers do not reproduce native source evidence.")
    for item in ledgers.values():
        batch = item.import_batch
        if (
            not batch.committed_at
            or item.maker_id == item.verifier_id
            or batch.verifier_id != item.verifier_id
            or batch.maker_id != item.maker_id
            or item.evidence_digest != digest(item.payload)
            or batch.file_digest
            != digest(
                {"rows": batch.source_rows, "schema": batch.schema_version, "reason": batch.reason}
            )
            or item.payload not in batch.preview
        ):
            gaps.append(
                "A ledger lacks consistent independently committed original batch evidence."
            )
    available_questions = {
        item.payload["question_id"]: item.payload["stage"]
        for item in ledgers.values()
        if not item.payload["void"]
    }
    maximum5 = sum(points_for_stage(round, stage) for stage in available_questions.values())
    if ledgers and maximum5 == 0:
        gaps.append("All questions are void; event adjudication is required before awards.")
    entries = []
    for team in Team.objects.filter(is_demo=round.is_demo, code__in=codes).order_by("code"):
        prior = carried.get(team.code, {"score": Decimal(0), "maximum": Decimal(0), "parts": {}})
        stages = {str(stage): 0 for stage in range(1, 6)}
        completions = []
        for ledger in ledgers.values():
            if ledger.payload["void"]:
                continue
            for row in ledger.payload["rows"]:
                if row["team_code"] == team.code:
                    stages[str(ledger.payload["stage"])] += row["points"]
                    if row["points"]:
                        completions.append(row["completed_at"])
        score5 = sum(stages.values())
        total = prior["score"] + Decimal(score5)
        entries.append(
            {
                "team_code": team.code,
                "team_name": team.name,
                "team_status": team.status,
                "eligible": team.code in codes and round_eligible(team, round),
                "stage_scores": stages,
                "round5_score": score5,
                "carry_over_scores": prior["parts"],
                "carry_over_score": float(prior["score"]),
                "score": float(total),
                **(
                    {"score_basis": "CUMULATIVE_RAW"}
                    if prior.get("maximum_is_storage_bound")
                    else {}
                ),
                "score_decimal": str(total),
                "max_score": float(prior["maximum"] + maximum5),
                "last_correct_at": max(completions) if completions else None,
                "tie_time_ms": None,
                "rank": None,
            }
        )
    comparable = {}
    for entry in entries:
        same_score = [
            item
            for item in entries
            if item["eligible"]
            and Decimal(item["score_decimal"]) == Decimal(entry["score_decimal"])
        ]
        comparable[entry["team_code"]] = (
            -Decimal(entry["score_decimal"]),
            entry["last_correct_at"] if all(item["last_correct_at"] for item in same_score) else "",
        )
    entries.sort(
        key=lambda entry: (
            not entry["eligible"],
            comparable[entry["team_code"]],
            entry["team_code"],
        )
    )
    eligible = [entry for entry in entries if entry["eligible"]]
    last, rank = None, 0
    for position, entry in enumerate(eligible, 1):
        metric = comparable[entry["team_code"]]
        if metric != last:
            rank = position
        entry["rank"], last = rank, metric
    tied = (
        [
            entry["team_code"]
            for entry in eligible
            if comparable[entry["team_code"]] == comparable[eligible[0]["team_code"]]
        ]
        if len(eligible) > 1
        else []
    )
    if len(tied) < 2:
        tied = []
    incidents = list(Incident.objects.filter(round=round).order_by("pk"))
    open_count = sum(item.material and item.closed_at is None for item in incidents)
    blockers = list(dict.fromkeys(configuration + gaps))
    if not eligible:
        blockers.append("An eligible finalist is required to award the event winner.")
    if open_count:
        blockers.append(f"{open_count} material incident(s) remain open.")
    if any(
        not rejected(batch)
        for batch in ImportBatch.objects.filter(round=round, committed_at__isnull=True)
    ):
        blockers.append("Review or reject pending source batches before final awards.")
    if tied:
        blockers.append(
            "An exact score/completion tie blocks final publication."
            if round.rules_snapshot.get("rules", {}).get("qualification_tie_policy")
            == "block_exact_ties"
            else "A winner cutoff tie needs independently reviewed reserve-question evidence."
        )
    latest = latest_snapshot(round)
    if not latest or latest.status != "PROVISIONAL":
        blockers.append("Publish provisional results before final awards.")
    else:
        if latest.ranked_entries != entries:
            blockers.append("Publish revised provisional results after changes; restart appeals.")
        if latest.appeal_deadline is None or now < latest.appeal_deadline:
            blockers.append("The published appeal window is still open.")
    if round.state == "FINALIZED":
        blockers.append("Final awards cannot be replaced through ordinary publication.")
    return {
        "round_id": round.pk,
        "number": 5,
        "attempt_no": round.attempt_no,
        "title": round.title,
        "state": round.state,
        "control_version": round.control_version,
        "entries": entries,
        "max_score": max((entry["max_score"] for entry in entries), default=0),
        "round5_max_score": maximum5,
        "cut_count": 1,
        "award_count": 1,
        "cutoff_tie": tied,
        "evidence_digest": digest(
            {
                "source": source_digest(round),
                "basis": basis,
                "phases": list(RoundPhase.objects.filter(round=round).values()),
            }
        ),
        "evidence_gaps": list(dict.fromkeys(gaps)),
        "configuration_errors": configuration,
        "finalization_blockers": list(dict.fromkeys(blockers)),
        "open_material_incidents": open_count,
        "appeal_deadline": latest.appeal_deadline.isoformat()
        if latest and latest.appeal_deadline
        else None,
        "ranking_kind": "BUZZER_FINAL",
    }
