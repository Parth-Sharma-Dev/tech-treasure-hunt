import runpy
from pathlib import Path

import pytest
from competition.models import ResultSnapshot, Round, Team
from django.contrib.auth import get_user_model
from django.core.management.base import CommandError
from django.utils import timezone

pytestmark = pytest.mark.django_db(transaction=True)
SCRIPT = Path(__file__).resolve().parents[2] / "tools" / "export_qualification_lists.py"


@pytest.fixture
def published():
    users = get_user_model()
    maker = users.objects.create_user(username="maker")
    reviewer = users.objects.create_user(username="reviewer")
    codes = [f"TEAM-{index:02}" for index in range(52)]
    for code in codes:
        Team.objects.create(
            code=code,
            name=f"Name {code}",
            member_count=3,
            user=users.objects.create_user(username=code),
        )
    snapshots = []
    for number, entrants, qualifiers in [(1, codes, codes[:50]), (2, codes[:44], codes[:20])]:
        round = Round.objects.create(number=number, title=f"Round {number}", state="FINALIZED")
        snapshots.append(
            ResultSnapshot.objects.create(
                round=round,
                revision=1,
                status="FINAL",
                qualifier_codes=qualifiers,
                ranked_entries=[
                    {
                        "team_code": code,
                        "team_name": f"Name {code}",
                        "score": 10,
                        "tie_time_ms": 100,
                        "rank": 1,
                    }
                    for code in reversed(entrants)
                ],
                maker=maker,
                approver=reviewer,
                published_at=timezone.now(),
            )
        )
    return snapshots


def export():
    return runpy.run_path(str(SCRIPT))["build_lists"]()


def test_reduced_cut_uses_lexical_ties_and_includes_absent_entrants(published):
    lists = export()

    def codes(key):
        return {row["team_code"] for row in lists[key]}

    assert [len(rows) for rows in lists.values()] == [7, 45, 25, 20]
    assert codes("round_2_qualified") == {f"TEAM-{index:02}" for index in range(45)}
    assert "TEAM-44" in codes("round_2_disqualified")  # Absent from R2 standings.
    assert "TEAM-45" in codes("round_1_disqualified")
    assert ResultSnapshot.objects.get(pk=published[0].pk).qualifier_codes == [
        f"TEAM-{index:02}" for index in range(50)
    ]


def test_latest_attempt_without_final_does_not_fall_back(published):
    Round.objects.create(number=1, attempt_no=2, title="Restart")
    with pytest.raises(CommandError, match="FINALIZED"):
        export()


def test_round2_qualifiers_outside_reduced_45_are_reported(published):
    ResultSnapshot.objects.filter(pk=published[1].pk).update(qualifier_codes=["TEAM-49"])
    with pytest.raises(CommandError, match="TEAM-49"):
        export()


def test_existing_45_qualifiers_are_preserved(published):
    keep = [f"TEAM-{index:02}" for index in range(44)] + ["TEAM-49"]
    ResultSnapshot.objects.filter(pk=published[0].pk).update(qualifier_codes=keep)
    lists = export()
    assert {row["team_code"] for row in lists["round_2_qualified"]} == set(keep)
