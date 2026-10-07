import uuid
from datetime import timedelta
from unittest.mock import patch

import pytest
from test_results import ended_hunt as _ended_hunt

from competition.api import ApiProblem
from competition.clock import control_round
from competition.models import Completion, PaperSlip, PaperWindow, Round
from competition.paper import approve_paper, end_paper, propose_paper
from competition.results import build_preview

pytestmark = pytest.mark.django_db
ended_hunt = _ended_hunt


@pytest.fixture
def paper_hunt(ended_hunt):
    round, _, _, _, _, start = ended_hunt
    Round.objects.filter(pk=round.pk).update(
        state="FROZEN", phase_started_at=start + timedelta(seconds=30), active_budget_ms=180000
    )
    round.refresh_from_db()
    return ended_hunt


def activate(hunt):
    round, _, teams, maker, reviewer, start = hunt
    request = {
        "action_id": str(uuid.uuid4()),
        "kind": "ACTIVATE",
        "reason": "Synthetic paper rehearsal",
        "expected_version": round.control_version,
        "assigned_desks": {team.code: "DESK-1" for team in teams},
        "clock_evidence": ["official-clock-check"],
        "writer_isolation_evidence": ["online-writing-disabled"],
        "evidence_refs": ["incident-sheet"],
    }
    proposed = propose_paper(round.pk, maker, request)
    review = {
        "action_id": str(uuid.uuid4()),
        "proposal_id": proposed["paper_proposal_id"],
        "reason": "Checked clock and isolation",
        "evidence_confirmed": True,
    }
    with pytest.raises(ApiProblem, match="different verifier"):
        approve_paper(round.pk, maker, review)
    with patch("competition.paper.database_now", return_value=start + timedelta(seconds=40)):
        result = approve_paper(round.pk, reviewer, review)
        assert approve_paper(round.pk, reviewer, review) == result
    round.refresh_from_db()
    return result


def slip(hunt, seconds, number, answer="0042", **extra):
    round, missions, teams, maker, reviewer, start = hunt
    when = start + timedelta(seconds=40 + seconds)
    request = {
        "action_id": str(uuid.uuid4()),
        "kind": "SLIP",
        "reason": "Synthetic numbered slip",
        "expected_version": round.control_version,
        "team_code": teams[0].code,
        "mission_id": missions[0].pk,
        "slip_number": number,
        "desk": "DESK-1",
        "evaluated_at": when.isoformat(),
        "answer": answer,
        "evidence_refs": ["slip-scan-" + number],
        **extra,
    }
    proposed = propose_paper(round.pk, maker, request)
    review = {
        "action_id": str(uuid.uuid4()),
        "proposal_id": proposed["paper_proposal_id"],
        "reason": "Compared original slip",
        "evidence_confirmed": True,
    }
    with patch("competition.paper.database_now", return_value=when + timedelta(seconds=1)):
        result = approve_paper(round.pk, reviewer, review)
        assert approve_paper(round.pk, reviewer, review) == result
    return result


def test_one_way_activation_preserves_online_clock_and_requires_distinct_reviewer(paper_hunt):
    round, _, _, maker, reviewer, start = paper_hunt
    activate(paper_hunt)
    window = PaperWindow.objects.get(round=round)
    assert window.active_offset_ms == 30000 and window.remaining_budget_ms == 150000
    assert window.recorder_id != window.verifier_id
    with pytest.raises(ApiProblem, match="paper play"):
        control_round(
            round.pk,
            maker,
            {
                "action": "resume",
                "action_id": str(uuid.uuid4()),
                "reason": "Attempt reopening",
                "expected_version": round.control_version,
            },
        )


def test_paper_limits_preserve_wrong_blocked_and_accepted_slips(paper_hunt):
    activate(paper_hunt)
    assert slip(paper_hunt, 5, "0001", answer="1024")["outcome"] == "incorrect"
    assert slip(paper_hunt, 10, "0002")["outcome"] == "blocked"
    accepted = slip(paper_hunt, 65, "0003")
    assert accepted["outcome"] == "accepted"
    item = Completion.objects.get()
    assert item.effective_active_ms == 95000
    with pytest.raises(ApiProblem, match="chronological"):
        slip(paper_hunt, 20, "0004")
    with pytest.raises(ApiProblem, match="already been reconciled"):
        slip(paper_hunt, 65, "0003")
    round, _, _, maker, _, start = paper_hunt
    with patch("competition.paper.database_now", return_value=start + timedelta(seconds=110)):
        end_paper(
            round.pk,
            maker,
            {
                "action_id": str(uuid.uuid4()),
                "expected_version": round.control_version,
                "reason": "Close synthetic paper play",
            },
        )
    round.refresh_from_db()
    # Reject failed proposals before finalization; they never award points.
    preview = build_preview(round, start + timedelta(seconds=111))
    assert preview["evidence_gaps"] == []
    assert preview["entries"][0]["score"] == 1
    assert PaperSlip.objects.count() == 3


def test_wrong_desk_and_future_time_cannot_score(paper_hunt):
    activate(paper_hunt)
    with pytest.raises(ApiProblem, match="desk assignment"):
        slip(paper_hunt, 5, "0001", desk="UNASSIGNED")
    with pytest.raises(ApiProblem, match="official time"):
        slip(paper_hunt, 151, "0002")
    assert not Completion.objects.exists()
