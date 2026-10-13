"""Import a private grading report through audited proposals and independent review.

Run from Django shell/runpy; no application redeployment is needed.
"""

import hashlib
import json
import os
import uuid
from pathlib import Path


def import_grades(
    path, operation, actor_name, maker_name="parth", review_confirmed=False
):
    from competition.coding_results import (
        approve_judgment,
        calculate_marks,
        propose_judgment,
    )
    from competition.models import AuditEvent, CodingJudgment, CodingSubmission, Round
    from competition.results import require_result_role
    from competition.rules import require_staff_permission
    from django.contrib.auth import get_user_model
    from django.db import transaction

    raw = Path(path).read_bytes()
    if len(raw) > 2_000_000:
        raise ValueError("Grading report exceeds 2 MB.")
    report = json.loads(raw)
    if operation not in ("propose", "approve"):
        raise ValueError("Choose propose or approve.")
    rows = report["teams"]
    if not rows or len({r["submission_id"] for r in rows}) != len(rows):
        raise ValueError("Supply distinct final submissions.")
    checksum = hashlib.sha256(raw).hexdigest()
    results = []
    with transaction.atomic():
        actor = get_user_model().objects.get(username=actor_name)
        maker = get_user_model().objects.get(username=maker_name)
        require_result_role(maker)
        if operation == "approve":
            require_staff_permission(actor, "verify_evidence")
            if actor.pk == maker.pk or not review_confirmed:
                raise ValueError(
                    "A different verifier must confirm independent source/test review."
                )
        elif actor.pk != maker.pk:
            raise ValueError("The proposing actor must be the declared maker.")
        round = Round.objects.select_for_update().get(
            pk=report["round_id"], number=3, is_demo=False
        )
        if round.state not in ("ENDED", "PROVISIONAL"):
            raise ValueError(
                "Use an ended real Round 3; finalized results are protected."
            )
        if report["cut"] != 11 or round.rules_snapshot.get("advancement_count") != 11:
            raise ValueError("The approved cut must remain eleven.")
        finals = {
            s.pk: s
            for s in CodingSubmission.objects.filter(round=round).select_related("team")
        }
        saved_ids = {pk for pk, s in finals.items() if s.kind != "NO_SUBMISSION"}
        if saved_ids != {r["submission_id"] for r in rows}:
            raise ValueError(
                "Report must cover every saved final submission exactly once."
            )
        # Validate the entire report before proposing or committing any marks.
        for row in rows:
            submission = finals[row["submission_id"]]
            if (
                submission.team.code != row["team_code"]
                or submission.submitted_at.isoformat() != row["submitted_at"]
            ):
                raise ValueError(
                    "Team or frozen final timestamp differs from the reviewed report."
                )
            if not submission.workstation_evidence.get("supervisor_id"):
                raise ValueError(
                    "A submission is missing recorded workstation/supervisor evidence."
                )
            score, correct, _ = calculate_marks(
                round, submission, row["suggested_task_grades"]
            )
            if score != row["score"] or correct != row["fully_correct_tasks"]:
                raise ValueError(
                    "Proposed totals do not reproduce the source-bound grades."
                )
        for row in rows:
            submission = finals[row["submission_id"]]
            action_id = str(
                uuid.uuid5(
                    uuid.NAMESPACE_URL,
                    f"tth-coding-propose:{round.attempt_id}:{checksum}:{maker.pk}:{submission.pk}",
                )
            )
            request = {
                "action_id": action_id,
                "reason": f"Reviewed grading report SHA256 {checksum}. Q1 assesses formula and explanation only.",
                "submission_id": submission.pk,
                "grades": row["suggested_task_grades"],
                "supervisor_id": submission.workstation_evidence["supervisor_id"],
                "supervisor_time": submission.submitted_at.isoformat(),
                "evidence_refs": [
                    f"grading-report:sha256:{checksum}",
                    "execution-results.json:Python3.13.13-GCC15.2.0-C99",
                ],
                "time_evidence": [
                    f"coding-submission:{submission.pk}:frozen-time",
                    f"coding-workstation:{submission.workstation_evidence.get('id')}:supervisor:{submission.workstation_evidence['supervisor_id']}",
                ],
            }
            if operation == "propose":
                if (
                    CodingJudgment.objects.filter(submission=submission).exists()
                    and not AuditEvent.objects.filter(action_id=action_id).exists()
                ):
                    raise ValueError(
                        "Existing lab judgments found; refusing an automatic replacement."
                    )
                outcome = propose_judgment(round.pk, actor, request)
            else:
                audit = AuditEvent.objects.filter(
                    action_id=action_id, actor=maker, action="propose_coding_judgment"
                ).first()
                if audit is None:
                    raise ValueError("Run the maker's complete proposal import first.")
                proposal_id = audit.after["response"]["judgment_proposal_id"]
                from competition.models import CodingJudgmentProposal

                proposal = CodingJudgmentProposal.objects.get(
                    pk=proposal_id, submission=submission
                )
                if proposal.payload["grades"] != request["grades"]:
                    raise ValueError("Proposal differs from the reviewed report.")
                reviewed = CodingJudgment.objects.filter(proposal=proposal).first()
                if reviewed:
                    if reviewed.rejected or reviewed.verifier_id != actor.pk:
                        raise ValueError(
                            "Proposal was rejected or reviewed by another account."
                        )
                    outcome = {
                        "judgment_id": reviewed.pk,
                        "score": str(reviewed.score),
                        "already_reviewed": True,
                    }
                else:
                    outcome = approve_judgment(
                        round.pk,
                        actor,
                        {
                            "action_id": str(
                                uuid.uuid5(
                                    uuid.NAMESPACE_URL,
                                    f"tth-coding-review:{checksum}:{actor.pk}:{proposal_id}",
                                )
                            ),
                            "reason": f"Independently reviewed source, tests, Q1 instruction and frozen times. Report SHA256 {checksum}.",
                            "proposal_id": proposal_id,
                            "evidence_confirmed": True,
                        },
                    )
            results.append({"team_code": row["team_code"], **outcome})
    return results


if __name__ == "__main__":
    print(
        json.dumps(
            import_grades(
                os.environ.get(
                    "TTH_GRADING_REPORT",
                    "/home/site/private-transfer/round3-grading-review.json",
                ),
                os.environ["TTH_GRADING_OPERATION"],
                os.environ["TTH_GRADING_ACTOR"],
                review_confirmed=os.environ.get("TTH_GRADING_REVIEW_CONFIRMED") == "1",
            ),
            indent=2,
        )
    )
