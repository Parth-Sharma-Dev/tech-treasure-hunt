"""Round 2 finish-time and Round 4 panel rubric ranking strategies."""

from decimal import Decimal

from .clock import milliseconds
from .external_scores import (
    current_scores,
    decimal_value,
    effective_question_score,
    schema_errors,
    validate_rows,
    voided_questions,
)
from .models import ImportBatch, Incident, Round, RoundPhase, ScoreRevision, Team
from .participant import round_eligible
from .results import digest, latest_snapshot
from .rules import snapshot_digest


def build_preview(round, now):
    rules = round.rules_snapshot.get("rules", {})
    from .green_cards import is_green_cards
    from .models import GreenCardRevision

    green = is_green_cards(round, rules)
    errors = schema_errors(round, rules)
    gaps = []
    phases = list(RoundPhase.objects.filter(round=round).order_by("started_at", "pk"))
    if round.state not in ["ENDED", "PROVISIONAL", "FINALIZED"] or any(
        [round.live_started_at, round.phase_started_at, round.deadline_at]
    ):
        gaps.append("End and persist the external round clock before publication.")
    if not round.rules_digest or snapshot_digest(round.rules_snapshot) != round.rules_digest:
        gaps.append("The frozen external rules digest is inconsistent.")
    if (
        not phases
        or not any(item.phase_type == "LIVE" for item in phases)
        or any(item.ended_at is None for item in phases)
        or sum(
            milliseconds(item.ended_at - item.started_at)
            for item in phases
            if item.phase_type == "LIVE" and item.ended_at
        )
        != round.accumulated_active_ms
        or any(
            left.ended_at != right.started_at
            for left, right in zip(phases, phases[1:], strict=False)
        )
    ):
        gaps.append("External clock intervals need reconciliation.")
    previous = (
        Round.objects.filter(number=round.number - 1, is_demo=round.is_demo)
        .order_by("-attempt_no")
        .first()
    )
    previous_final = latest_snapshot(previous) if previous else None
    if (
        not previous
        or previous.state != "FINALIZED"
        or not previous_final
        or previous_final.status != "FINAL"
        or Incident.objects.filter(round=previous, material=True, closed_at__isnull=True).exists()
    ):
        gaps.append(f"Round {round.number - 1} final qualification needs review.")
    teams = list(Team.objects.filter(is_demo=round.is_demo).order_by("code"))
    scores = current_scores(round)
    maximum = rules.get("score_schema", {}).get("max_score", "0")
    try:
        maximum = Decimal(maximum)
        if not maximum.is_finite():
            maximum = Decimal(0)
    except Exception:
        maximum = Decimal(0)
    if round.number == 2 and not errors:
        maximum -= len(voided_questions(round))
    entries, metrics = [], {}
    for team in teams:
        eligible = round_eligible(team, round)
        revision = scores.get(team.pk)
        if eligible and revision is None:
            gaps.append(
                f"{team.code} needs reviewed score evidence, including explicit zero marks."
            )
        averages = {}
        criterion_sums = {}
        finish = None
        received = False
        score = revision.score if revision else Decimal(0)
        if revision:
            batch = revision.import_batch
            if (
                not batch
                or not batch.committed_at
                or batch.verifier_id != revision.verifier_id
                or batch.maker_id != revision.maker_id
                or revision.verifier_id == revision.maker_id
            ):
                gaps.append("A score revision lacks its independently committed source batch.")
            elif not errors and eligible:
                source, invalid = validate_rows(round, batch.source_rows, enforce_eligibility=False)
                row = next((item for item in source if item["team_code"] == team.code), None)
                if invalid or row is None or Decimal(row["score"]) != revision.score:
                    gaps.append("Source marks no longer reproduce the reviewed total.")
                if row and (
                    Decimal(row["max_score"]) != revision.max_score
                    or row["tie_metrics"] != revision.tie_metrics
                ):
                    gaps.append("Reviewed maximum or tie metrics differ from source evidence.")
                if batch.file_digest != digest(
                    {
                        "rows": batch.source_rows,
                        "schema": batch.schema_version,
                        "reason": batch.reason,
                    }
                ):
                    gaps.append("The original source batch digest is inconsistent.")
            if revision.max_score != Decimal(rules.get("score_schema", {}).get("max_score", "0")):
                gaps.append("A reviewed score uses the wrong approved maximum.")
            if round.number == 2:
                if not errors:
                    try:
                        score, _ = effective_question_score(round, revision.tie_metrics)
                    except ValueError:
                        gaps.append("Round 2 question credit evidence is malformed.")
                finish = revision.tie_metrics.get("official_finish_active_ms")
                if type(finish) is not int or not 0 <= finish <= round.active_budget_ms:
                    gaps.append("Round 2 official finish evidence is missing or invalid.")
                    finish = None
            elif green:
                received = revision.received
            else:
                averages = revision.tie_metrics.get("averages", {})
                criterion_sums = revision.tie_metrics.get("criterion_sums", {})
                try:
                    if not isinstance(averages, dict) or set(averages) != {
                        "technical",
                        "problem_solving",
                        "communication",
                        "coordination",
                    }:
                        raise ValueError()
                    for value in averages.values():
                        decimal_value(value, Decimal(10))
                    if not isinstance(criterion_sums, dict) or set(criterion_sums) != set(averages):
                        raise ValueError()
                    for value in criterion_sums.values():
                        decimal_value(value, Decimal(30))
                except ValueError:
                    gaps.append("Faculty criterion averages are missing or malformed.")
                    averages = {}
                    criterion_sums = {}
        metric = (
            (-int(received),)
            if green
            else (
                (-score, finish if finish is not None else 10**15)
                if round.number == 2
                else (
                    -score,
                    -Decimal(criterion_sums.get("technical", "0")),
                    -Decimal(criterion_sums.get("problem_solving", "0")),
                )
            )
        )
        metrics[team.code] = metric
        entries.append(
            {
                "team_code": team.code,
                "team_name": team.name,
                "team_status": team.status,
                "eligible": eligible,
                "score": float(score),
                "max_score": float(maximum),
                "tie_time_ms": finish,
                **({"official_finish_active_ms": finish} if round.number == 2 else {}),
                "criterion_averages": averages if round.number == 4 else None,
                **({"green_card": received} if green else {}),
                "rank": None,
            }
        )
    entries.sort(
        key=lambda item: (not item["eligible"], metrics[item["team_code"]], item["team_code"])
    )
    eligible = [item for item in entries if item["eligible"]]
    last, rank = None, 0
    for position, entry in enumerate(eligible, 1):
        if green:
            continue
        metric = metrics[entry["team_code"]]
        if metric != last:
            rank = position
        entry["rank"], last = rank, metric
    cut, tied = round.rules_snapshot.get("advancement_count"), []
    if type(cut) is not int or cut <= 0:
        errors.append("Set a positive approved advancement count.")
    elif green:
        if sum(entry["green_card"] for entry in eligible) > cut:
            errors.append("Green Card recipients exceed the approved advancement count.")
    elif len(eligible) < cut and rules.get("short_roster_policy") != "advance_all_eligible":
        errors.append("Approve a short-roster policy before advancing fewer teams than the cut.")
    elif (
        0 < cut < len(eligible)
        and metrics[eligible[cut - 1]["team_code"]] == metrics[eligible[cut]["team_code"]]
    ):
        boundary = metrics[eligible[cut - 1]["team_code"]]
        tied = [item["team_code"] for item in eligible if metrics[item["team_code"]] == boundary]
    latest = latest_snapshot(round)
    blockers = list(dict.fromkeys(gaps + errors))
    incidents = list(Incident.objects.filter(round=round).order_by("pk"))
    open_count = sum(item.material and item.closed_at is None for item in incidents)
    if open_count:
        blockers.append(f"{open_count} material incident(s) remain open.")
    from .external_scores import AuditEventRejected

    if any(
        not AuditEventRejected(batch)
        for batch in ImportBatch.objects.filter(round=round, committed_at__isnull=True)
    ):
        blockers.append("Review or reject pending source batches before finalization.")
    from .models import AuditEvent, ExternalQuestionVoid, ExternalVoidProposal

    reviewed_voids = AuditEvent.objects.filter(
        action="external_question_void", after__request__round_id=round.pk
    ).values_list("after__response__reviewed_proposal_id", flat=True)
    if (
        ExternalVoidProposal.objects.filter(round=round)
        .exclude(pk__in=[value for value in reviewed_voids if value])
        .exists()
    ):
        blockers.append("Review or reject pending question voids before finalization.")
    if tied:
        blockers.append(
            "An exact external rubric tie blocks final publication."
            if rules.get("qualification_tie_policy") == "block_exact_ties"
            else "A qualification cutoff tie requires reviewed common reserve-question evidence."
        )
    if not latest or latest.status != "PROVISIONAL":
        blockers.append("Publish provisional results before finalization.")
    else:
        if latest.ranked_entries != entries:
            blockers.append("Publish revised provisional results after changes; restart appeals.")
        if latest.appeal_deadline is None or now < latest.appeal_deadline:
            blockers.append("The published appeal window is still open.")
    if round.state == "FINALIZED":
        blockers.append("Final results cannot be replaced through ordinary publication.")
    evidence = {
        "rules": round.rules_digest,
        "teams": list(Team.objects.filter(is_demo=round.is_demo).order_by("pk").values()),
        "scores": list(
            (GreenCardRevision if green else ScoreRevision)
            .objects.filter(round=round)
            .order_by("pk")
            .values()
        ),
        "batches": list(ImportBatch.objects.filter(round=round).order_by("pk").values()),
        "phases": list(RoundPhase.objects.filter(round=round).order_by("pk").values()),
        "incidents": list(Incident.objects.filter(round=round).order_by("pk").values()),
        "previous_final": previous_final.pk if previous_final else None,
    }
    evidence["voids"] = list(
        ExternalQuestionVoid.objects.filter(proposal__round=round).order_by("pk").values()
    )
    evidence["void_proposals"] = list(
        ExternalVoidProposal.objects.filter(round=round).order_by("pk").values()
    )
    return {
        "round_id": round.pk,
        "number": round.number,
        "attempt_no": round.attempt_no,
        "title": round.title,
        "state": round.state,
        "control_version": round.control_version,
        "rules_digest": round.rules_digest,
        "evidence_digest": digest(evidence),
        "entries": entries,
        "cut_count": cut,
        "cutoff_tie": tied,
        "max_score": float(maximum),
        "open_material_incidents": open_count,
        "evidence_gaps": list(dict.fromkeys(gaps)),
        "configuration_errors": errors,
        "finalization_blockers": blockers,
        "latest_snapshot_id": latest.pk if latest else None,
        "appeal_deadline": latest.appeal_deadline.isoformat()
        if latest and latest.appeal_deadline
        else None,
        "server_time": now.isoformat(),
        "ranking_kind": "GREEN_CARDS"
        if green
        else "FACULTY"
        if round.number == 4
        else "EXTERNAL_FINISH",
    }
