import uuid
from datetime import timedelta
from unittest.mock import patch

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
    round.active_budget_ms = 300000
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


def played(final, count=1, winners=None, end=True):
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
    if end:
        control_round(
            round.pk, final[3], action(action="end", expected_version=round.control_version)
        )
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


def publish(final, status="PROVISIONAL", **extra):
    from competition.results import approve_result, build_preview, propose_result

    round = final[0]
    round.refresh_from_db()
    preview = build_preview(round, timezone.now())
    proposal = propose_result(
        round.pk,
        final[3],
        action(
            status=status,
            expected_version=round.control_version,
            evidence_digest=preview["evidence_digest"],
            evidence_confirmed=True,
            **extra,
        ),
    )
    return approve_result(
        round.pk, final[4], action(proposal_id=proposal["proposal_id"], evidence_confirmed=True)
    )


def test_complete_final_has_fifty_marks_carry_over_and_one_winner_not_round6(final):
    from competition.results import build_preview

    rows = played(final, count=25)
    intake(final, rows)
    preview = build_preview(final[0], timezone.now())
    assert preview["evidence_gaps"] == [] and preview["configuration_errors"] == []
    assert preview["round5_max_score"] == 50
    assert preview["entries"][0]["round5_score"] == 50 and preview["entries"][0]["score"] == 70
    assert list(preview["entries"][0]["stage_scores"].values()) == [10] * 5
    publish(final)
    snapshot = ResultSnapshot.objects.filter(round=final[0]).latest("revision")
    when = snapshot.appeal_deadline + timedelta(seconds=1)
    with patch("competition.results.database_now", return_value=when):
        round = final[0]
        round.refresh_from_db()
        preview = build_preview(round, when)
        from competition.results import approve_result, propose_result

        proposal = propose_result(
            round.pk,
            final[3],
            action(
                status="FINAL",
                expected_version=round.control_version,
                evidence_digest=preview["evidence_digest"],
                evidence_confirmed=True,
            ),
        )
        result = approve_result(
            round.pk, final[4], action(proposal_id=proposal["proposal_id"], evidence_confirmed=True)
        )
    assert result["qualifier_codes"] == [] and result["winner_codes"] == [final[2][0].code]
    winner = ResultSnapshot.objects.filter(round=round).latest("revision")
    assert (
        winner.qualifier_codes == []
        and winner.metadata["winner_title"] == "The Winner of Tech Treasure Hunt"
    )
    assert "private answer" not in str(winner.ranked_entries) and round.advancement_count is None


def test_missing_question_coverage_blocks_publication(final):
    from competition.results import build_preview

    intake(final, played(final, count=1))
    preview = build_preview(final[0], timezone.now())
    assert any("All 25" in message for message in preview["evidence_gaps"])
    with pytest.raises(ApiProblem, match="All 25"):
        publish(final)


def test_equal_cumulative_scores_rank_by_last_correct_completion_not_buzz_time(final):
    from competition.results import build_preview

    rows = played(final, count=25, winners=[0, 1] + [0] * 23)
    for row in rows:
        if row["window_id"] != rows[0]["window_id"] and row["window_id"] != rows[2]["window_id"]:
            row["verdict"] = "VOID"
            row["adjudication_reference"] = "synthetic-faulty-question-report"
    intake(final, rows)
    preview = build_preview(final[0], timezone.now())
    first, second = preview["entries"]
    assert first["score"] == second["score"] == 22
    assert (
        first["team_code"] == final[2][0].code
        and first["last_correct_at"] < second["last_correct_at"]
    )
    assert not preview["cutoff_tie"]


def test_carry_over_can_outweigh_the_round5_score(final):
    from competition.results import build_preview

    snapshot = ResultSnapshot.objects.filter(round__number=4).latest("revision")
    entries = snapshot.ranked_entries
    entries[1]["score"] = 40
    ResultSnapshot.objects.create(
        round=snapshot.round,
        revision=3,
        status="FINAL",
        ranked_entries=entries,
        qualifier_codes=snapshot.qualifier_codes,
        maker=final[3],
        approver=final[4],
        published_at=timezone.now(),
    )
    rows = played(final, count=25)
    for row in rows[2:]:
        row["verdict"] = "VOID"
        row["adjudication_reference"] = "synthetic-cancelled-question"
    intake(final, rows)
    first = build_preview(final[0], timezone.now())["entries"][0]
    assert (
        first["team_code"] == final[2][1].code
        and first["round5_score"] == 0
        and first["score"] == 52
    )


def test_score_routes_require_staff_csrf_and_never_accept_imported_time_or_marks(final):
    rows = played(final)
    client = client_for(final)
    base = f"/api/staff/rounds/{final[0].pk}"
    assert client.get(base + "/imports").status_code == 403
    assert post(client, base + "/buzzer/answer", action()).status_code == 403
    from django.test import Client

    from competition.buzzer_scores import validate_import

    staff = Client(enforce_csrf_checks=True)
    staff.force_login(final[3])
    assert (
        staff.post(base + "/imports/validate", {}, content_type="application/json").status_code
        == 403
    )
    rows[0]["points"] = 999
    batch = validate_import(final[0].pk, final[3], action(schema_version="round5-v1", rows=rows))
    assert batch["errors"] and not BuzzerScoreRevision.objects.exists()


def test_carry_over_change_stales_pending_batch_and_unreviewed_batches_block_award(final):
    from competition.buzzer_scores import commit_import, validate_import
    from competition.results import build_preview

    rows = played(final, count=25)
    batch = validate_import(final[0].pk, final[3], action(schema_version="round5-v1", rows=rows))
    snapshot = ResultSnapshot.objects.filter(round__number=1).latest("revision")
    ResultSnapshot.objects.create(
        round=snapshot.round,
        revision=2,
        status="FINAL",
        ranked_entries=snapshot.ranked_entries,
        qualifier_codes=snapshot.qualifier_codes,
        maker=final[3],
        approver=final[4],
        published_at=timezone.now(),
    )
    with pytest.raises(ApiProblem, match="changed"):
        commit_import(
            final[0].pk, final[4], action(batch_id=batch["batch_id"], evidence_confirmed=True)
        )
    assert any(
        "pending source batches" in message
        for message in build_preview(final[0], timezone.now())["finalization_blockers"]
    )


def test_revised_credit_restarts_provisional_appeal_requirement(final):
    from competition.results import build_preview

    rows = played(final, count=25)
    intake(final, rows)
    publish(final)
    rows[0]["verdict"] = "WRONG"
    rows[0]["adjudication_reference"] = "reviewed-original-judgment-correction"
    intake(final, rows)
    assert any(
        "revised provisional" in message
        for message in build_preview(final[0], timezone.now())["finalization_blockers"]
    )


def test_native_drafts_preserve_adjudicated_equal_time_order_for_uncalled_teams(final):
    from competition.buzzer_scores import source_context
    from competition.clock import control_round

    round = start(final)
    window = open_window(final)
    clients = [client_for(final, index) for index in range(2)]
    with patch("competition.buzzer.database_now", return_value=timezone.now()):
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
    order = [team.code for team in final[2][:2]]
    record_answer(
        round.pk,
        final[3],
        action(
            window_id=window["id"],
            press_id=receipts[0]["id"],
            verdict="CORRECT",
            answer="private answer",
            source_reference="synthetic-host-sheet",
            buzzer_order=order,
            adjudication_reference="synthetic-buzzer-tie-review",
        ),
    )
    control_round(round.pk, final[3], action(action="end", expected_version=round.control_version))
    round.refresh_from_db()
    rows = source_context(round)["draft_source_rows"]
    assert all(row["buzzer_tie_order"] == "|".join(order) for row in rows)
    rows[1]["verdict"], rows[1]["source_reference"] = "NOT_CALLED", "synthetic-uncalled-sheet"
    intake(final, rows)


def test_round5_cannot_enter_the_legacy_unlinked_external_scoring_service():
    from competition.external_scores import require_external

    with pytest.raises(ApiProblem, match="Round 2 and Round 4"):
        require_external(Round(number=5, delivery_mode="EXTERNAL"))


def test_scoring_seed_preserves_content_and_never_fabricates_final_scores(buzzer, settings):
    from django.core.management import call_command

    settings.DEBUG = True
    before = ResultSnapshot.objects.count()
    call_command("seed_buzzer_scoring_demo", actor=buzzer[3].username)
    assert BuzzerQuestion.objects.count() == 25 and ResultSnapshot.objects.count() == before
    call_command("seed_buzzer_scoring_demo", actor=buzzer[3].username)
    assert BuzzerQuestion.objects.count() == 25
    assert (
        BuzzerQuestion.objects.get(pk=buzzer[1][0].pk).private_content["answer"] == "SECRET-ANSWER"
    )


@pytest.mark.django_db(transaction=True)
def test_real_browser_final_scores_and_independent_winner_publication(final, live_server):
    import os
    import shutil
    import subprocess
    from pathlib import Path

    from competition.clock import database_now

    if os.environ.get("TTH_BROWSER_INTEGRATION") != "1":
        pytest.skip("Opt-in: actual browser and PostgreSQL final-score journey.")
    played(final, count=24, end=False)
    open_window(final, question=24)

    def publication_now():
        latest = (
            ResultSnapshot.objects.filter(round=final[0], status="PROVISIONAL")
            .order_by("-revision")
            .first()
        )
        return latest.appeal_deadline + timedelta(seconds=1) if latest else database_now()

    with (
        patch("competition.results.database_now", side_effect=publication_now),
        patch("competition.results_views.database_now", side_effect=publication_now),
    ):
        result = subprocess.run(
            [shutil.which("node"), "frontend/scripts/live-final-scores-smoke.mjs"],
            cwd=Path(__file__).resolve().parents[2],
            capture_output=True,
            text=True,
            timeout=120,
            env={
                **os.environ,
                "TTH_BACKEND_URL": live_server.url.replace("localhost", "127.0.0.1"),
                "TTH_FINAL_ROUND": str(final[0].pk),
            },
        )
    assert result.returncode == 0, result.stdout + result.stderr
    snapshot = ResultSnapshot.objects.filter(round=final[0]).latest("revision")
    assert snapshot.status == "FINAL" and snapshot.qualifier_codes == []
    assert snapshot.metadata["winner_codes"] == [final[2][0].code]
    assert BuzzerScoreRevision.objects.count() == 25


def test_missing_last_correct_times_hold_equal_cumulative_scores_for_review(final):
    from competition.results import build_preview

    rows = played(final, count=25)
    for row in rows:
        if row["verdict"] == "CORRECT":
            row["verdict"] = "WRONG"
            row["adjudication_reference"] = "synthetic-review-no-credit"
    intake(final, rows)
    preview = build_preview(final[0], timezone.now())
    assert len(preview["cutoff_tie"]) == 2 and all(
        entry["rank"] == 1 for entry in preview["entries"]
    )
