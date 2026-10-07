import hmac

from .answers import answer_digest
from .api import ApiProblem
from .clock import clock_payload, database_now
from .models import Incident, Mission, ResultSnapshot, Round, Team


def round_eligible(team, round):
    if team.status != Team.Status.ACTIVE or team.is_demo != round.is_demo:
        return False
    if round.number == 1:
        return True
    previous = (
        Round.objects.filter(number=round.number - 1, is_demo=team.is_demo)
        .order_by("-attempt_no")
        .first()
    )
    if previous is None or previous.state != Round.State.FINALIZED:
        return False
    if Incident.objects.filter(
        round=previous, category="QUALIFICATION_IMPACT", closed_at__isnull=True
    ).exists():
        return False
    if Incident.objects.filter(
        round=round, category="QUALIFICATION_IMPACT", closed_at__isnull=True
    ).exists():
        return False
    snapshot = ResultSnapshot.objects.filter(round=previous).order_by("-revision").first()
    return (
        snapshot is not None
        and snapshot.status == "FINAL"
        and team.code in snapshot.qualifier_codes
    )


def public_rules(round):
    if round.state == Round.State.DRAFT or not round.rules_snapshot:
        return None
    rules = round.rules_snapshot["rules"]
    return {
        key: rules[key]
        for key in (
            "allowed_tools",
            "movement_policy",
            "appeal_minutes",
            "ranking_policy",
            "qualification_tie_policy",
            "paper_attempt_policy",
            "points_per_mission",
            "free_wrong_attempts",
            "cooldown_seconds",
            "team_answer_limit",
            "team_answer_window_ms",
        )
        if key in rules
    }


def participant_rounds(team):
    now = database_now()
    rounds = Round.objects.filter(is_demo=team.is_demo).order_by("number", "-attempt_no")
    latest = {}
    for round in rounds:
        if round.number not in latest:
            latest[round.number] = {
                "id": round.pk,
                "number": round.number,
                "title": round.title,
                "state": clock_payload(round, now)["state"],
                "clock": clock_payload(round, now),
                "eligible": round_eligible(team, round),
                "rules_version": round.rules_version if round.state != Round.State.DRAFT else None,
                "rules": public_rules(round),
            }
    return list(latest.values())


def practice_mission(team):
    round = Round.objects.filter(number=1, is_demo=team.is_demo).order_by("-attempt_no").first()
    mission = (
        Mission.objects.filter(round=round, is_practice=True, available=True, is_void=False)
        .order_by("pk")
        .first()
    )
    if mission is None:
        raise ApiProblem("practice_unavailable", "The practice clue is not available yet.", 404)
    return mission


def practice_answer(team, answer):
    mission = practice_mission(team)
    if (
        not isinstance(answer, str)
        or len(answer) != 4
        or any(char not in "0123456789" for char in answer)
    ):
        raise ApiProblem(
            "invalid_format", "Enter exactly four digits, including any leading zeros."
        )
    accepted = any(
        hmac.compare_digest(
            answer_digest(mission.pk, verifier["version"], answer), verifier["digest"]
        )
        for verifier in mission.answer_verifiers
    )
    return {
        "outcome": "accepted" if accepted else "incorrect",
        "practice_only": True,
        "points_awarded": 0,
        "keyword": mission.keyword if accepted else None,
    }
