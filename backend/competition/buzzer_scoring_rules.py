"""The organizer's fixed 25-question, two-mark cumulative final contract."""

LEGACY_CONTRACT = {
    "version": "round5-v1",
    "questions_per_stage": 5,
    "points_per_correct": 2,
    "wrong_points": 0,
    "unanswered_points": 0,
    "max_score": 50,
    "answer_passing": "buzzer_queue",
    "winner_count": 1,
    "carry_over": "sum_final_rounds_1_to_4",
    "tie_break": "last_correct_completion",
}

CONTRACT = {
    **LEGACY_CONTRACT,
    "version": "round5-v2",
    "max_score": 30,
    "carry_over": "sum_final_rounds_1_to_3",
    "points_per_stage": {"1": 1, "2": 1, "3": 1, "4": 1, "5": 2},
}
CONTRACT.pop("points_per_correct")


def contract_for(round):
    schema = round.rules_snapshot.get("rules", round.rules).get("score_schema", {})
    return LEGACY_CONTRACT if schema.get("version") == "round5-v1" else CONTRACT


def points_for_stage(round, stage):
    contract = contract_for(round)
    return contract.get("points_per_stage", {}).get(
        str(stage), contract.get("points_per_correct", 1)
    )


def reveal_stage(round):
    return 5 if contract_for(round) is LEGACY_CONTRACT else 4


def schema_errors(round, rules=None):
    rules = round.rules if rules is None else rules
    schema = rules.get("score_schema")
    expected = (
        LEGACY_CONTRACT
        if isinstance(schema, dict) and schema.get("version") == "round5-v1"
        else CONTRACT
    )
    if (
        not isinstance(schema, dict)
        or schema != expected
        or any(type(schema.get(key)) is not type(value) for key, value in expected.items())
        or "points_per_stage" in schema
        and any(type(value) is not int for value in schema["points_per_stage"].values())
    ):
        return [
            "Configure round5-v2: 5 questions/stage, 1 mark in stages 1–4, 2 in stage 5, 30 total."
        ]
    errors = []
    if rules.get("ranking_policy") != "cumulative_score_then_last_correct":
        errors.append("Use cumulative_score_then_last_correct ranking.")
    if rules.get("qualification_tie_policy") not in [
        "supervised_reserve_question",
        "block_exact_ties",
    ]:
        errors.append("Declare an unresolved equal-completion tie policy.")
    from .models import BuzzerQuestion

    counts = [
        BuzzerQuestion.objects.filter(round=round, stage=stage).count() for stage in range(1, 6)
    ]
    if counts != [5] * 5:
        errors.append(
            "Round 5 requires exactly five verified questions in each of its five stages."
        )
    return errors
