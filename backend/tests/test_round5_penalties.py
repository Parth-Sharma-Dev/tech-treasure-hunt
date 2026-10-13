import uuid

import pytest
from django.utils import timezone
from test_buzzer import action, client_for, open_window, post, start
from test_buzzer import buzzer as _buzzer
from test_buzzer_scores import final as _final

from competition.api import ApiProblem
from competition.buzzer import control_window, queue
from competition.buzzer_answers import record_answer
from competition.buzzer_scores import commit_import, source_context, validate_import
from competition.buzzer_scoring_rules import PENALTY_CONTRACT
from competition.clock import control_round
from competition.models import BuzzerPress, BuzzerPrompt
from competition.results import build_preview

pytestmark = pytest.mark.django_db
buzzer = _buzzer
final = _final


@pytest.fixture
def penalties(final):
    round = final[0]
    round.rules = {
        **round.rules,
        "score_schema": dict(PENALTY_CONTRACT),
        "ranking_policy": "round5_score_then_last_correct",
        "buzzer_early_policy": "penalize_before_host_go",
    }
    round.save()
    return final


def tap(fixture, client, window):
    data = {"action_id": str(uuid.uuid4()), "window_id": window["id"]}
    response = post(client, f"/api/rounds/{fixture[0].pk}/buzzer/press", data)
    assert response.status_code == 200
    assert post(client, f"/api/rounds/{fixture[0].pk}/buzzer/press", data).json() == response.json()
    return response.json()["press"]


def signal(fixture, operation):
    round = fixture[0]
    from competition.buzzer import latest_window

    window = latest_window(round)
    data = action(
        operation=operation,
        expected_version=round.control_version,
        expected_window_version=window.version,
    )
    response = control_window(round.pk, fixture[3], data)
    assert control_window(round.pk, fixture[3], data) == response
    return response


def score(fixture, verdicts):
    round = fixture[0]
    control_round(
        round.pk, fixture[3], action(action="end", expected_version=round.control_version)
    )
    round.refresh_from_db()
    rows = source_context(round)["draft_source_rows"]
    for row in rows:
        if not row["verdict"]:
            row["verdict"] = verdicts[row["team_code"]]
            row["source_reference"] = "Synthetic native window review"
    batch = validate_import(round.pk, fixture[3], action(schema_version="round5-v4", rows=rows))
    assert batch["errors"] == []
    commit_import(round.pk, fixture[4], action(batch_id=batch["batch_id"], evidence_confirmed=True))
    round.refresh_from_db()
    return batch, build_preview(round, timezone.now())


def test_early_buzz_is_once_only_then_go_allows_valid_buzz_and_wrong_stops_passing(penalties):
    round = start(penalties)
    window = open_window(penalties)
    clients = [client_for(penalties, i) for i in range(2)]
    for _ in range(2):
        assert tap(penalties, clients[0], window)["is_early"] is True
    assert (
        queue(BuzzerPrompt._meta.get_field("window").related_model.objects.get(pk=window["id"]))[0]
        == []
    )
    before = clients[0].get(f"/api/rounds/{round.pk}/buzzer").json()
    assert before["own_early_press"] and not before["can_press"]
    signal(penalties, "go")
    assert clients[0].get(f"/api/rounds/{round.pk}/buzzer").json()["can_press"]
    first = tap(penalties, clients[1], window)
    second = tap(penalties, clients[0], window)
    assert first["is_early"] is second["is_early"] is False
    signal(penalties, "close")
    record_answer(
        round.pk,
        penalties[3],
        action(
            window_id=window["id"],
            press_id=first["id"],
            verdict="WRONG",
            answer="Wrong response",
            source_reference="Synthetic host sheet",
        ),
    )
    with pytest.raises(ApiProblem, match="passing is disabled"):
        record_answer(
            round.pk,
            penalties[3],
            action(
                window_id=window["id"],
                press_id=second["id"],
                verdict="CORRECT",
                answer="Correct response",
                source_reference="Synthetic host sheet",
            ),
        )
    batch, preview = score(penalties, {penalties[2][0].code: "NOT_CALLED"})
    points = {r["team_code"]: r for r in batch["preview"][0]["rows"]}
    assert points[penalties[2][0].code]["points"] == -1
    assert points[penalties[2][0].code]["early_penalty"] == -1
    assert points[penalties[2][1].code]["points"] == -1
    assert all(e["score"] == -1 and e["last_correct_at"] is None for e in preview["entries"])
    assert BuzzerPress.objects.filter(is_early=True).count() == 2


def test_early_then_correct_word_encoding_is_two_minus_one_and_keeps_completion(penalties):
    round = start(penalties)
    window = open_window(penalties, question=4)
    client = client_for(penalties)
    assert tap(penalties, client, window)["is_early"]
    signal(penalties, "go")
    press = tap(penalties, client, window)
    signal(penalties, "close")
    record_answer(
        round.pk,
        penalties[3],
        action(
            window_id=window["id"],
            press_id=press["id"],
            verdict="CORRECT",
            answer="Correct response",
            source_reference="Synthetic host sheet",
        ),
    )
    _, preview = score(penalties, {penalties[2][1].code: "NO_BUZZ"})
    first = preview["entries"][0]
    assert first["score"] == 1 and first["carry_over_score"] == 0
    assert first["last_correct_at"] is not None


def test_penalty_configuration_remains_unapproved(penalties):
    from django.core.management import call_command

    from competition.models import Round

    round = Round.objects.create(number=5, attempt_no=2, is_demo=False)
    call_command("configure_round5_only", actor=penalties[3].username, penalties=True)
    round.refresh_from_db()
    assert round.rules["score_schema"]["wrong_points"] == -1
    assert round.rules["score_schema"]["early_points"] == -1
    assert round.rules["score_schema"]["carry_over"] == "none"
    assert round.rules["score_schema"]["answer_passing"] == "first_team_only"
    assert round.rules["buzzer_early_policy"] == "penalize_before_host_go"
    assert round.state == "DRAFT" and round.approved_at is None
