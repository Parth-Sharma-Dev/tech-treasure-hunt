"""Organizer-approved timing/cuts for new real drafts; content release stays separate."""

COMMON = {
    "route_reference": "event-20261012-route-plan",
    "accessibility_policy": "Request an approved accessible route or workstation assistance.",
    "qualification_tie_policy": "supervised_reserve_question",
    "appeal_minutes": 5,
    "paper_attempt_policy": "pause_and_review_for_independent_pool_or_external_quiz",
    "unresolved_data_policy": "suspend_for_review",
    "retention_days": 30,
    "short_roster_policy": "advance_all_eligible",
}

ROUND1_RULES = {
    **COMMON,
    "allowed_tools": ["Contest website, QR scanner and organizer-issued codes"],
    "movement_policy": "Stay together and follow the organizer-approved campus route.",
    "qualification_tie_policy": "supervised_reserve_clue",
    "delivery_instructions": (
        "Open a mission before submitting a six-character code. Preserve punctuation; "
        "letter case is ignored. Each team may claim at most three distinct unclaimed codes."
    ),
    "ranking_policy": "score_then_last_active_completion",
    "code_mode": "independent_pool",
    "answer_format": "six_printable_ascii",
    "max_code_claims": 3,
    "points_per_code": 1,
    "expected_code_count": 168,
    "expected_mission_count": 25,
    "max_team_sessions": 1,
    "free_wrong_attempts": 5,
    "cooldown_seconds": [30, 60, 120, 240, 300],
    "team_answer_limit": 10,
    "team_answer_window_ms": 60000,
    "cutoff_policy": "database_admission_no_grace",
    "registration_cap": 110,
    "peak_browser_count": 112,
}

ROUND2_RULES = {
    **COMMON,
    "allowed_tools": ["Wayground quiz and contest website as instructed by organizers"],
    "movement_policy": "Use the assigned supervised quiz workstation or venue.",
    "delivery_instructions": (
        "Record earned keywords before the quiz starts. Quiz answers are submitted in "
        "Wayground; reviewed final website results determine qualification."
    ),
    "ranking_policy": "wayground_score_then_answer_time",
    "score_schema": {
        "version": "round2-wayground-v2",
        "max_score": "9999999.999",
        "maximum_is_storage_bound": True,
        "question_count": 30,
        "score_metric": "wayground_score",
        "time_metric": "reported_answer_duration",
        "source_sheet": "Participant Data",
    },
}
