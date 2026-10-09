import uuid

import pytest
from django.utils import timezone
from test_buzzer import action, client_for, open_window, post, start
from test_buzzer import buzzer as _buzzer

from competition.api import ApiProblem
from competition.buzzer import control_window
from competition.buzzer_answers import record_answer
from competition.buzzer_scoring_rules import CONTRACT, schema_errors
from competition.models import (
    BuzzerAnswerEvidence,
    BuzzerQuestion,
    BuzzerScoreRevision,
    ResultSnapshot,
    Round,
)

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
    for number in range(1, 5):
        previous = Round.objects.filter(number=number, is_demo=True).first()
        if previous is None:
            previous = Round.objects.create(
                number=number,
                title=f"Synthetic carry-over {number}",
                is_demo=True,
                state="FINALIZED",
            )
        ResultSnapshot.objects.create(
            round=previous,
            revision=2 if number == 4 else 1,
            status="FINAL",
            ranked_entries=[
                {"team_code": team.code, "score": number * 2, "max_score": 100, "eligible": True}
                for team in teams[:2]
            ],
            qualifier_codes=[team.code for team in teams[:2]],
            maker=maker,
            approver=reviewer,
            published_at=timezone.now(),
        )
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


def played(final, count=1, winners=None):
    from competition.clock import control_round

    round = start(final)
    clients = [client_for(final, index) for index in range(2)]
    rows = []
    for index in range(count):
        window = open_window(final, question=index)
        winner = winners[index] if winners else 0
        receipt = post(
            clients[winner],
            f"/api/rounds/{round.pk}/buzzer/press",
            {"action_id": str(uuid.uuid4()), "window_id": window["id"]},
        ).json()["press"]
        control_window(
            round.pk,
            final[3],
            action(
                operation="close",
                expected_version=round.control_version,
                expected_window_version=window["version"],
            ),
        )
        note = record_answer(
            round.pk,
            final[3],
            action(
                window_id=window["id"],
                press_id=receipt["id"],
                verdict="CORRECT",
                answer="private answer",
                source_reference="synthetic-host-sheet",
            ),
        )
        for team_index, team in enumerate(final[2][:2]):
            called = team_index == winner
            rows.append(
                {
                    "window_id": window["id"],
                    "team_code": team.code,
                    "press_id": receipt["id"] if called else "",
                    "answer_evidence_id": note["answer_evidence_id"] if called else "",
                    "verdict": "CORRECT" if called else "NO_BUZZ",
                    "answer": "private answer" if called else "",
                    "reveal_step": "0",
                    "buzzer_tie_order": "",
                    "adjudication_reference": "",
                    "source_reference": "synthetic-offline-sheet",
                }
            )
    round.refresh_from_db()
    control_round(round.pk, final[3], action(action="end", expected_version=round.control_version))
    round.refresh_from_db()
    return rows


def intake(final, rows):
    from competition.buzzer_scores import commit_import, validate_import

    round = final[0]
    batch = validate_import(round.pk, final[3], action(schema_version="round5-v1", rows=rows))
    assert batch["errors"] == []
    review = action(batch_id=batch["batch_id"], evidence_confirmed=True)
    result = commit_import(round.pk, final[4], review)
    assert commit_import(round.pk, final[4], review) == result
    round.refresh_from_db()
    return batch


def test_reviewed_ledger_is_atomic_independent_and_idempotent(final):
    from competition.buzzer_scores import carry_over, commit_import, validate_import

    rows = played(final)
    assert carry_over(final[0])[1][final[2][0].code]["score"] == 20
    batch = validate_import(final[0].pk, final[3], action(schema_version="round5-v1", rows=rows))
    assert not BuzzerScoreRevision.objects.exists()
    with pytest.raises(ApiProblem, match="different verifier"):
        commit_import(
            final[0].pk, final[3], action(batch_id=batch["batch_id"], evidence_confirmed=True)
        )
    intake(final, rows)
    assert BuzzerScoreRevision.objects.count() == 1
    assert BuzzerScoreRevision.objects.get().payload["rows"][0]["points"] == 2


def test_invalid_native_source_or_incomplete_window_never_commits(final):
    from competition.buzzer_scores import commit_import, validate_import

    rows = played(final)
    rows[0]["answer"] = "invented response"
    batch = validate_import(final[0].pk, final[3], action(schema_version="round5-v1", rows=rows))
    assert batch["errors"]
    with pytest.raises(ApiProblem, match="All source rows"):
        commit_import(
            final[0].pk, final[4], action(batch_id=batch["batch_id"], evidence_confirmed=True)
        )
    assert not BuzzerScoreRevision.objects.exists()


def test_corrections_append_and_retain_original_completion_time(final):
    rows = played(final)
    intake(final, rows)
    original = BuzzerScoreRevision.objects.get()
    rows[0]["verdict"] = "WRONG"
    rows[0]["adjudication_reference"] = "reviewed-answer-correction"
    intake(final, rows)
    revised = BuzzerScoreRevision.objects.order_by("-pk").first()
    assert revised.supersedes_id == original.pk and BuzzerScoreRevision.objects.count() == 2
    assert original.payload["rows"][0]["completed_at"] == revised.payload["rows"][0]["completed_at"]
    assert original.payload["rows"][0]["points"] == 2 and revised.payload["rows"][0]["points"] == 0
