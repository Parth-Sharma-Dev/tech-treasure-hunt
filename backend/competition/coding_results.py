"""Lab evidence is independently reviewed; ranking uses frozen submitted source."""

from datetime import UTC, datetime
from decimal import ROUND_HALF_UP, Decimal

from django.db import transaction
from django.utils.dateparse import parse_datetime

from .api import ApiProblem
from .clock import milliseconds
from .coding import latest_revisions, native_round, source_hash
from .corrections import evidence_refs
from .models import (
    AuditEvent,
    CodingJudgment,
    CodingJudgmentProposal,
    CodingRevision,
    CodingSubmission,
    Incident,
    Round,
    RoundPhase,
    Team,
)
from .participant import round_eligible
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


def latest_grade(submission):
    return (
        CodingJudgment.objects.filter(submission=submission, rejected=False).order_by("-pk").first()
    )


def grading_digest(round, submission):
    grade = latest_grade(submission)
    return digest(
        {
            "rules": round.rules_digest,
            "manifest": submission.manifest,
            "station": submission.workstation_evidence,
            "submitted_at": submission.submitted_at,
            "kind": submission.kind,
            "previous_grade": grade.pk if grade else None,
        }
    )


def calculate_marks(round, submission, grades):
    tasks = round.rules_snapshot["coding_tasks"]
    if (
        not isinstance(grades, list)
        or len(grades) != len(tasks)
        or any(
            not isinstance(item, dict) or type(item.get("task_id")) is not int for item in grades
        )
    ):
        raise ApiProblem("invalid_grades", "Supply one grade for every released task.")
    by_id = {item["task_id"]: item for item in grades}
    if set(by_id) != {task["id"] for task in tasks} or len(by_id) != len(grades):
        raise ApiProblem("invalid_grades", "Task grades must be complete and unique.")
    sources = {item["task_id"]: item for item in submission.manifest}
    marks = []
    for task in tasks:
        grade = by_id[task["id"]]
        source = sources.get(task["id"])
        if grade.get("task_version") != task["version"] or grade.get("source_hash") != (
            source["source_hash"] if source else ""
        ):
            raise ApiProblem(
                "stale_evidence",
                "Bind each grade to the frozen task version and submitted source hash.",
                409,
            )
        maximum = Decimal(task["points"])
        if task["category"] == "SHORT":
            passed = grade.get("passed_tests")
            test_ids = {case["id"] for case in task["private_rubric"]["test_cases"]}
            if (
                not isinstance(passed, list)
                or any(not isinstance(value, str) for value in passed)
                or len(set(passed)) != len(passed)
                or not set(passed) <= test_ids
            ):
                raise ApiProblem(
                    "invalid_grades", "Select unique passed IDs from the fixed hidden tests."
                )
            if passed and source is None:
                raise ApiProblem("invalid_grades", "Unsaved tasks cannot earn marks.")
            points = (maximum * Decimal(len(passed)) / Decimal(len(test_ids))).quantize(
                Decimal("0.001"), rounding=ROUND_HALF_UP
            )
            correct = len(passed) == len(test_ids)
        else:
            correct = grade.get("correct")
            if type(correct) is not bool or (correct and source is None):
                raise ApiProblem(
                    "invalid_grades",
                    "Non-coding-task categories use all-or-nothing marks on saved responses.",
                )
            points = maximum if correct else Decimal(0)
        marks.append(
            {
                "task_id": task["id"],
                "points": str(points),
                "maximum": str(maximum),
                "correct": correct,
            }
        )
    return (
        sum(Decimal(item["points"]) for item in marks),
        sum(item["correct"] for item in marks),
        marks,
    )


@transaction.atomic
def propose_judgment(round_id, actor, data):
    require_result_role(actor)
    action_id, reason = validate_request(data)
    round = locked_round(round_id)
    native_round(round)
    fingerprint = {
        **data,
        "kind": "coding_judgment_propose",
        "round_id": round_id,
        "actor_id": actor.pk,
    }
    if replay := audit_replay(action_id, fingerprint):
        return replay
    if round.state not in ["ENDED", "PROVISIONAL"]:
        raise ApiProblem(
            "invalid_transition", "End coding play before proposing lab judgments.", 409
        )
    submission = (
        CodingSubmission.objects.filter(pk=data.get("submission_id"), round=round).first()
        if type(data.get("submission_id")) is int
        else None
    )
    if submission is None or submission.kind == "NO_SUBMISSION":
        raise ApiProblem("not_found", "Saved final submission not found.", 404)
    score, correct, marks = calculate_marks(round, submission, data.get("grades"))
    try:
        observed = parse_datetime(data.get("supervisor_time", ""))
    except (ValueError, TypeError):
        observed = None
    if observed != submission.submitted_at or data.get(
        "supervisor_id"
    ) != submission.workstation_evidence.get("supervisor_id"):
        raise ApiProblem(
            "time_evidence_required",
            "Confirm the frozen final time and assigned supervisor identity.",
        )
    payload = {
        "grades": data["grades"],
        "score": str(score),
        "fully_correct_tasks": correct,
        "task_marks": marks,
        "evidence_refs": evidence_refs(data),
        "time_evidence": evidence_refs({"evidence_refs": data.get("time_evidence")}),
        "supervisor_id": data["supervisor_id"],
        "supervisor_time": submission.submitted_at.isoformat(),
    }
    proposal = CodingJudgmentProposal.objects.create(
        submission=submission,
        maker=actor,
        payload=payload,
        reason=reason,
        evidence_digest=grading_digest(round, submission),
    )
    response = {
        "judgment_proposal_id": proposal.pk,
        "score": str(score),
        "fully_correct_tasks": correct,
    }
    record_action(action_id, actor, "propose_coding_judgment", reason, fingerprint, response)
    return response


@transaction.atomic
def approve_judgment(round_id, actor, data):
    require_staff_permission(actor, "verify_evidence")
    action_id, reason = validate_request(data)
    round = locked_round(round_id)
    native_round(round)
    fingerprint = {
        **data,
        "kind": "coding_judgment_approve",
        "round_id": round_id,
        "actor_id": actor.pk,
    }
    if replay := audit_replay(action_id, fingerprint):
        return replay
    proposal = (
        CodingJudgmentProposal.objects.select_related("submission", "maker")
        .filter(pk=data.get("proposal_id"), submission__round=round)
        .first()
        if type(data.get("proposal_id")) is int
        else None
    )
    if proposal is None:
        raise ApiProblem("not_found", "Judgment proposal not found.", 404)
    if proposal.maker_id == actor.pk:
        raise ApiProblem(
            "independent_reviewer", "A different verifier must review the lab judgment.", 403
        )
    if (
        round.state not in ["ENDED", "PROVISIONAL"]
        or CodingJudgment.objects.filter(proposal=proposal).exists()
    ):
        raise ApiProblem(
            "invalid_transition", "Review a pending judgment before final publication.", 409
        )
    if data.get("evidence_confirmed") is not True:
        raise ApiProblem(
            "evidence_required",
            "Confirm independent review of source, tests, scores and supervisor time.",
        )
    rejected = data.get("reject") is True
    if not rejected:
        require_result_role(proposal.maker)
        if proposal.evidence_digest != grading_digest(round, proposal.submission):
            raise ApiProblem(
                "stale_evidence", "Judging evidence changed; reject and remake this proposal.", 409
            )
        score, correct, marks = calculate_marks(
            round, proposal.submission, proposal.payload["grades"]
        )
    else:
        score, correct, marks = Decimal(0), 0, []
    judgment = CodingJudgment.objects.create(
        proposal=proposal,
        submission=proposal.submission,
        verifier=actor,
        score=score,
        fully_correct_tasks=correct,
        task_marks=marks,
        rejected=rejected,
    )
    round.control_version += 1
    round.save(update_fields=["control_version"])
    response = {
        "judgment_id": judgment.pk,
        "rejected": rejected,
        "score": str(score),
        "fully_correct_tasks": correct,
    }
    record_action(action_id, actor, "review_coding_judgment", reason, fingerprint, response)
    return response


def build_preview(round, now):
    native_round(round)
    phases = list(RoundPhase.objects.filter(round=round).order_by("started_at", "pk"))
    submissions = list(
        CodingSubmission.objects.filter(round=round).select_related("team").order_by("pk")
    )
    teams = list(Team.objects.filter(is_demo=round.is_demo).order_by("code"))
    incidents = list(Incident.objects.filter(round=round).order_by("pk"))
    gaps = []
    if (
        round.state not in ["ENDED", "PROVISIONAL", "FINALIZED"]
        or round.live_started_at
        or round.phase_started_at
        or round.deadline_at
    ):
        gaps.append("End and persist the coding clock before publication.")
    if snapshot_digest(round.rules_snapshot) != round.rules_digest:
        gaps.append("The frozen coding rules digest is inconsistent.")
    if (
        not phases
        or sum(
            milliseconds(item.ended_at - item.started_at)
            for item in phases
            if item.phase_type == "LIVE"
        )
        != round.accumulated_active_ms
    ):
        gaps.append("Coding clock intervals do not match persisted active time.")
    if any(
        left.ended_at != right.started_at for left, right in zip(phases, phases[1:], strict=False)
    ):
        gaps.append("Coding clock coverage has a gap or overlap.")
    previous = Round.objects.filter(number=2, is_demo=round.is_demo).order_by("-attempt_no").first()
    previous_final = latest_snapshot(previous) if previous else None
    if (
        previous is None
        or previous.state != "FINALIZED"
        or previous_final is None
        or previous_final.status != "FINAL"
        or Incident.objects.filter(round=previous, material=True, closed_at__isnull=True).exists()
    ):
        gaps.append("Round 2 final qualification needs organizer review.")
    by_team = {item.team_id: item for item in submissions}
    for submission in submissions:
        if submission.manifest_digest != digest(submission.manifest):
            gaps.append("A frozen source manifest is damaged.")
        seen = set()
        for item in submission.manifest:
            revision = CodingRevision.objects.filter(
                pk=item.get("revision_id"),
                round=round,
                team=submission.team,
                task_id=item.get("task_id"),
            ).first()
            if (
                revision is None
                or revision.source_hash != source_hash(revision.body)
                or revision.source_hash != item.get("source_hash")
                or revision.revision != item.get("revision")
                or revision.language != item.get("language")
                or revision.admitted_at > submission.submitted_at
                or item["task_id"] in seen
            ):
                gaps.append("A final bundle has missing, changed or late source evidence.")
            seen.add(item["task_id"])
        if seen != set(latest_revisions(round, submission.team, submission.submitted_at)):
            gaps.append("A frozen bundle does not include every last acknowledged response.")
        elapsed = sum(
            milliseconds(min(phase.ended_at, submission.submitted_at) - phase.started_at)
            for phase in phases
            if phase.phase_type == "LIVE" and phase.started_at <= submission.submitted_at
        )
        if submission.active_elapsed_ms != elapsed or not any(
            phase.started_at <= submission.submitted_at <= phase.ended_at for phase in phases
        ):
            gaps.append("A final submission has inconsistent official timing evidence.")
        if not submission.manifest and submission.kind != "NO_SUBMISSION":
            gaps.append("Empty work must retain an explicit no-submission outcome.")
        if (
            submission.manifest
            and not AuditEvent.objects.filter(
                action="assign_coding_workstation",
                actor_id=submission.workstation_evidence.get("supervisor_id"),
                after__response__station_id=submission.workstation_evidence.get("id"),
                after__response__version=submission.workstation_evidence.get("version"),
                after__request__session_id=submission.workstation_evidence.get("session_id"),
            ).exists()
        ):
            gaps.append("A saved bundle is missing its supervised workstation evidence.")
        if submission.manifest and latest_grade(submission) is None:
            gaps.append(
                f"{submission.team.code} still needs an independently reviewed lab judgment."
            )
    entries = []
    metrics = {}
    for team in teams:
        submission = by_team.get(team.pk)
        eligible = round_eligible(team, round)
        grade = latest_grade(submission) if submission else None
        if eligible and submission is None:
            gaps.append(f"{team.code} is missing its cutoff/no-submission record.")
        if grade:
            expected = calculate_marks(round, submission, grade.proposal.payload["grades"])
            if (
                grade.verifier_id == grade.proposal.maker_id
                or grade.score != expected[0]
                or grade.fully_correct_tasks != expected[1]
                or grade.task_marks != expected[2]
            ):
                gaps.append("Reviewed lab marks do not match frozen task/test evidence.")
            if parse_datetime(
                grade.proposal.payload["supervisor_time"]
            ) != submission.submitted_at or grade.proposal.payload[
                "supervisor_id"
            ] != submission.workstation_evidence.get("supervisor_id"):
                gaps.append("Supervisor final-time evidence changed after score review.")
        score = grade.score if grade else Decimal(0)
        correct = grade.fully_correct_tasks if grade else 0
        final_time = (
            submission.submitted_at if submission and submission.kind != "NO_SUBMISSION" else None
        )
        metrics[team.code] = (score, correct, final_time)
        entries.append(
            {
                "team_code": team.code,
                "team_name": team.name,
                "team_status": team.status,
                "eligible": eligible,
                "score": float(score),
                "max_score": 100,
                "fully_correct_tasks": correct,
                "final_submission_at": final_time.isoformat() if final_time else None,
                "tie_time_ms": submission.active_elapsed_ms if final_time else None,
                "rank": None,
            }
        )
    entries.sort(
        key=lambda item: (
            not item["eligible"],
            -metrics[item["team_code"]][0],
            -metrics[item["team_code"]][1],
            metrics[item["team_code"]][2] or datetime.max.replace(tzinfo=UTC),
            item["team_code"],
        )
    )
    eligible_entries = [item for item in entries if item["eligible"]]
    last_metric = None
    rank = 0
    for position, item in enumerate(eligible_entries, 1):
        metric = metrics[item["team_code"]]
        if metric != last_metric:
            rank = position
        item["rank"] = rank
        last_metric = metric
    cut = round.rules_snapshot.get("advancement_count")
    errors = []
    tied = []
    if type(cut) is not int or cut <= 0:
        errors.append("Set a positive approved advancement count.")
    elif (
        len(eligible_entries) < cut
        and round.rules_snapshot["rules"].get("short_roster_policy") != "advance_all_eligible"
    ):
        errors.append("The short roster needs an approved advance-all-eligible policy.")
    elif (
        0 < cut < len(eligible_entries)
        and metrics[eligible_entries[cut - 1]["team_code"]]
        == metrics[eligible_entries[cut]["team_code"]]
    ):
        boundary = metrics[eligible_entries[cut - 1]["team_code"]]
        tied = [
            item["team_code"] for item in eligible_entries if metrics[item["team_code"]] == boundary
        ]
    blockers = list(dict.fromkeys(gaps + errors))
    open_count = sum(item.material and item.closed_at is None for item in incidents)
    if open_count:
        blockers.append(f"{open_count} material incident(s) remain open.")
    pending = CodingJudgmentProposal.objects.filter(
        submission__round=round, codingjudgment__isnull=True
    ).exists()
    if pending:
        blockers.append("Review or reject pending lab judgments before finalization.")
    if tied:
        blockers.append(
            "An exact score/task/time tie blocks final publication under approved rules."
            if round.rules_snapshot["rules"].get("qualification_tie_policy") == "block_exact_ties"
            else "A qualification cutoff tie requires reviewed reserve-task evidence."
        )
    latest = latest_snapshot(round)
    if latest and latest.status == "PROVISIONAL":
        fields = [
            "team_code",
            "team_status",
            "eligible",
            "score",
            "max_score",
            "fully_correct_tasks",
            "final_submission_at",
            "rank",
        ]
        old_metrics = [{key: item.get(key) for key in fields} for item in latest.ranked_entries]
        new_metrics = [{key: item.get(key) for key in fields} for item in entries]
        if old_metrics != new_metrics:
            blockers.append(
                "Publish revised provisional coding results after scoring changes; restart appeals."
            )
    if latest is None or latest.status != "PROVISIONAL":
        blockers.append("Publish provisional results before finalization.")
    elif latest.appeal_deadline is None or now < latest.appeal_deadline:
        blockers.append("The published appeal window is still open.")
    evidence = {
        "rules": round.rules_digest,
        "teams": [{"code": item.code, "status": item.status} for item in teams],
        "submissions": list(CodingSubmission.objects.filter(round=round).order_by("pk").values()),
        "revisions": list(CodingRevision.objects.filter(round=round).order_by("pk").values()),
        "judgments": list(
            CodingJudgment.objects.filter(submission__round=round).order_by("pk").values()
        ),
        "proposals": list(
            CodingJudgmentProposal.objects.filter(submission__round=round).order_by("pk").values()
        ),
        "phases": list(RoundPhase.objects.filter(round=round).order_by("pk").values()),
        "incidents": list(Incident.objects.filter(round=round).order_by("pk").values()),
        "previous_final": previous_final.pk if previous_final else None,
    }
    return {
        "round_id": round.pk,
        "number": 3,
        "attempt_no": round.attempt_no,
        "title": round.title,
        "state": round.state,
        "control_version": round.control_version,
        "rules_digest": round.rules_digest,
        "evidence_digest": digest(evidence),
        "entries": entries,
        "cut_count": cut,
        "cutoff_tie": tied,
        "max_score": 100,
        "open_material_incidents": open_count,
        "evidence_gaps": list(dict.fromkeys(gaps)),
        "configuration_errors": errors,
        "finalization_blockers": blockers,
        "latest_snapshot_id": latest.pk if latest else None,
        "appeal_deadline": latest.appeal_deadline.isoformat()
        if latest and latest.appeal_deadline
        else None,
        "server_time": now.isoformat(),
        "ranking_kind": "CODING",
    }
