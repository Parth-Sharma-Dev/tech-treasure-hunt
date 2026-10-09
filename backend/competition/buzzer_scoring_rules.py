"""The organizer's fixed 25-question, two-mark cumulative final contract."""

CONTRACT = {
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


def schema_errors(round, rules=None):
    rules = round.rules if rules is None else rules
    schema = rules.get("score_schema")
    if (
        not isinstance(schema, dict)
        or schema != CONTRACT
        or any(type(schema.get(key)) is not type(value) for key, value in CONTRACT.items())
    ):
        return [
            "Configure round5-v1: 5 questions/stage, 2 marks, no penalties, passing and one winner."
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
