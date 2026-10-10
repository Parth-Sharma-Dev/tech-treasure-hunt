"""A complete independently reviewed recipient list determines qualification, never points."""

from .models import Round, Team
from .participant import round_eligible
from .results import latest_snapshot

SCHEMA = {
    "version": "round4-green-card-v2",
    "max_score": "0",
    "qualification_only": True,
    "carry_over_points": 0,
}


def is_green_cards(round, rules=None):
    rules = rules if rules is not None else round.rules_snapshot.get("rules", round.rules)
    return round.number == 4 and rules.get("score_schema", {}).get("version") == SCHEMA["version"]


def validate_names(round, rows, enforce_eligibility=True):
    teams = list(Team.objects.filter(is_demo=round.is_demo).order_by("code"))
    previous = Round.objects.filter(number=3, is_demo=round.is_demo).order_by("-attempt_no").first()
    final = latest_snapshot(previous) if previous else None
    pool = set(final.qualifier_codes) if final and final.status == "FINAL" else set()
    errors, selected = [], set()
    for index, row in enumerate(rows, 1):
        try:
            if not isinstance(row, dict) or set(row) != {"team_name"}:
                raise ValueError("Supply only team_name for each Green Card recipient.")
            name = row["team_name"]
            if not isinstance(name, str) or not name.strip() or len(name) > 200:
                raise ValueError("Supply a nonblank team name or code, at most 200 characters.")
            code_matches = [t for t in teams if t.code.casefold() == name.strip().casefold()]
            matches = code_matches or [
                t for t in teams if t.name.casefold() == name.strip().casefold()
            ]
            if len(matches) != 1:
                raise ValueError("Team name is unknown or ambiguous; use its unique team code.")
            team = matches[0]
            if team.code not in pool or enforce_eligibility and not round_eligible(team, round):
                raise ValueError("Recipient must be active and finally qualified from Round 3.")
            if team.code in selected:
                raise ValueError("Duplicate Green Card recipient.")
            selected.add(team.code)
        except ValueError as error:
            errors.append({"row": index, "message": str(error)})
    cut = round.rules_snapshot.get("advancement_count", round.advancement_count)
    if type(cut) is not int or len(selected) > cut:
        errors.append({"message": "Green Card recipients exceed the approved advancement count."})
    if not pool:
        errors.append({"message": "Round 3 needs a final reviewed qualifying list."})
    # Frozen policy treats this as a complete list; all unlisted entrants explicitly get no card.
    preview = [
        {
            "team_code": t.code,
            "score": "0",
            "max_score": "0",
            "tie_metrics": {"green_card": t.code in selected},
            "source_reference": "Complete reviewed Green Card recipient list",
        }
        for t in teams
        if t.code in pool
    ]
    return preview, errors
