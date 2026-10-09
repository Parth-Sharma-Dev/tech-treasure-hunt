import uuid

import pytest
from django.utils import timezone
from test_buzzer import action, client_for, open_window, post, start
from test_buzzer import buzzer as _buzzer

from competition.api import ApiProblem
from competition.buzzer import control_window
from competition.buzzer_answers import record_answer
from competition.buzzer_scoring_rules import CONTRACT, schema_errors
from competition.models import BuzzerAnswerEvidence, BuzzerQuestion

pytestmark = pytest.mark.django_db
buzzer = _buzzer


@pytest.fixture
def final(buzzer):
    round, questions, teams, maker, reviewer = buzzer
    for stage in range(1, 6):
        for number in range(2, 6):
            questions.append(
                BuzzerQuestion.objects.create(
                    round=round,
                    stage=stage,
                    public_id=f"STAGE-{stage}-Q{number}",
                    version="question-v1",
                    source_reference="synthetic-pack",
                    private_content={
                        "answer": "private answer",
                        "presentation_reference": "private image",
                    },
                    prepared_by=maker,
                    verified_by=reviewer,
                    verified_at=timezone.now(),
                )
            )
    round.rules = {
        **round.rules,
        "score_schema": dict(CONTRACT),
        "ranking_policy": "cumulative_score_then_last_correct",
        "qualification_tie_policy": "supervised_reserve_question",
    }
    round.save()
    return round, questions, teams, maker, reviewer


def test_confirmed_contract_requires_twenty_five_questions_and_no_negative_marks(final):
    assert schema_errors(final[0]) == []
    final[0].rules["score_schema"]["wrong_points"] = -1
    assert schema_errors(final[0])
    final[0].rules["score_schema"]["wrong_points"] = 0
    final[1][-1].delete()
    assert any("five" in error for error in schema_errors(final[0]))


def test_live_host_record_captures_server_completion_and_passes_only_after_wrong(final):
    round = start(final)
    window = open_window(final)
    clients = [client_for(final, index) for index in range(2)]
    receipts = [
        post(
            client,
            f"/api/rounds/{round.pk}/buzzer/press",
            {"action_id": str(uuid.uuid4()), "window_id": window["id"]},
        ).json()["press"]
        for client in clients
    ]
    control_window(
        round.pk,
        final[3],
        action(
            operation="close", expected_version=round.control_version, expected_window_version=1
        ),
    )
    second = action(
        window_id=window["id"],
        press_id=receipts[1]["id"],
        verdict="CORRECT",
        answer="private answer",
        source_reference="host-sheet",
    )
    with pytest.raises(ApiProblem, match="earlier buzzing team"):
        record_answer(round.pk, final[3], second)
    first = action(
        window_id=window["id"],
        press_id=receipts[0]["id"],
        verdict="WRONG",
        answer="wrong",
        source_reference="host-sheet",
    )
    noted = record_answer(round.pk, final[3], first)
    assert record_answer(round.pk, final[3], first) == noted
    assert record_answer(round.pk, final[3], second)["answer_evidence_id"]
    assert BuzzerAnswerEvidence.objects.count() == 2
    item = BuzzerAnswerEvidence.objects.get(pk=noted["answer_evidence_id"])
    assert item.completed_at >= item.press.received_at
    with pytest.raises(ApiProblem, match="server records completion"):
        record_answer(round.pk, final[3], {**second, "completed_at": "1999-01-01"})
