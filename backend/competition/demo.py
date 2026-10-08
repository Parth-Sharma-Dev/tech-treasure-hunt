def demo_rules(number):
    """Fictional configuration for local exploration, never official event rules."""
    rules = {
        "demo_only": True,
        "allowed_tools": ["synthetic demonstration materials"],
        "movement_policy": "stay_together",
        "route_reference": "synthetic-demo-route",
        "accessibility_policy": "No physical travel required for these synthetic clues.",
        "qualification_tie_policy": "supervised_reserve_clue",
        "appeal_minutes": 10,
        "paper_attempt_policy": "one_per_team_mission_per_60_active_seconds",
        "unresolved_data_policy": "suspend_for_review",
        "retention_days": 30,
        "delivery_instructions": "Local demo only; not instructions for the real event.",
        "ranking_policy": "score_then_last_active_completion"
        if number == 1
        else "external_demo_rubric",
    }
    if number == 1:
        rules.update(
            {
                "points_per_mission": 1,
                "max_team_sessions": 4,
                "answer_format": "four_ascii_digits",
                "free_wrong_attempts": 5,
                "cooldown_seconds": [30, 60, 120, 240, 300],
                "team_answer_limit": 10,
                "team_answer_window_ms": 60_000,
                "cutoff_policy": "database_admission_no_grace",
                "registration_cap": 2,
                "peak_browser_count": 8,
                "expected_mission_count": 2,
            }
        )
    else:
        rules["score_schema"] = {
            "demo_only": True,
            "score": "nonnegative_number",
            "max_score": "positive_number",
            "official_finish_active_ms": "nonnegative_integer",
        }
    if number == 2:
        rules["ranking_policy"] = "score_then_finish_time"
        rules["qualification_tie_policy"] = "supervised_reserve_question"
        rules["score_schema"] = {
            "version": "round2-v1",
            "max_score": "30",
            "question_ids": [f"Q{i:02}" for i in range(1, 31)],
        }
    return rules
