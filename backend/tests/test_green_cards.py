from datetime import timedelta
from unittest.mock import patch

import pytest
from django.utils import timezone
from test_external_scores import action, end
from test_external_scores import external as _external
from test_later_round_recovery import recover

from competition.api import ApiProblem
from competition.evidence import make_bundle
from competition.external_scores import commit_import, validate_import
from competition.green_cards import SCHEMA
from competition.models import GreenCardRevision, ResultSnapshot, Round, ScoreRevision
from competition.results import approve_result, build_preview, propose_result

pytestmark = pytest.mark.django_db
external = _external


@pytest.fixture
def cards(external):
    quiz, teams, maker, verifier = external
    previous = Round.objects.create(
        number=3, title="Prior qualification", is_demo=True, state="FINALIZED"
    )
    ResultSnapshot.objects.create(
        round=previous,
        revision=1,
        status="FINAL",
        qualifier_codes=[t.code for t in teams],
        maker=maker,
        approver=verifier,
        published_at=timezone.now(),
    )
    round = Round.objects.create(
        number=4,
        title="Green Card fixture",
        is_demo=True,
        delivery_mode="EXTERNAL",
        active_budget_ms=60000,
        advancement_count=2,
        owners=quiz.owners,
        rules_version="green-v2",
        rules={
            **quiz.rules,
            "score_schema": dict(SCHEMA),
            "ranking_policy": "green_card_qualification",
        },
    )
    fixture = round, teams, maker, verifier
    end(fixture)
    return fixture


def intake(cards, names):
    round, _, maker, verifier = cards
    batch = validate_import(
        round.pk,
        maker,
        action(
            schema_version=SCHEMA["version"],
            rows=[{"team_name": name} for name in names],
            complete_list_confirmed=True,
        ),
    )
    assert batch["errors"] == []
    review = action(batch_id=batch["batch_id"], evidence_confirmed=True)
    with pytest.raises(ApiProblem, match="different verifier"):
        commit_import(round.pk, maker, review)
    result = commit_import(round.pk, verifier, review)
    assert commit_import(round.pk, verifier, review) == result
    round.refresh_from_db()


def publish(cards, status, now):
    round, _, maker, verifier = cards
    preview = build_preview(round, now)
    proposed = propose_result(
        round.pk,
        maker,
        action(
            status=status,
            expected_version=round.control_version,
            evidence_digest=preview["evidence_digest"],
            evidence_confirmed=True,
        ),
    )
    approve_result(
        round.pk, verifier, action(proposal_id=proposed["proposal_id"], evidence_confirmed=True)
    )
    round.refresh_from_db()


def test_names_only_cards_qualify_exactly_listed_team_with_zero_points(cards):
    from django.utils import timezone

    round, teams, _, _ = cards
    intake(cards, [teams[0].name.lower()])
    assert GreenCardRevision.objects.count() == 3 and ScoreRevision.objects.count() == 0
    preview = build_preview(round, timezone.now())
    assert preview["ranking_kind"] == "GREEN_CARDS" and not preview["evidence_gaps"]
    assert all(entry["score"] == 0 and entry["max_score"] == 0 for entry in preview["entries"])
    assert preview["cutoff_tie"] == []
    publish(cards, "PROVISIONAL", timezone.now())
    deadline = ResultSnapshot.objects.filter(round=round).latest("revision").appeal_deadline
    with patch("competition.results.database_now", return_value=deadline + timedelta(seconds=1)):
        publish(cards, "FINAL", deadline + timedelta(seconds=1))
    assert ResultSnapshot.objects.filter(round=round).latest("revision").qualifier_codes == [
        teams[0].code
    ]


@pytest.mark.parametrize(
    "names", [["unknown"], ["EXT-0", "External 0"], ["EXT-0", "EXT-1", "EXT-2"]]
)
def test_unknown_duplicate_and_excess_card_recipients_cannot_commit(cards, names):
    round, _, maker, verifier = cards
    batch = validate_import(
        round.pk,
        maker,
        action(
            schema_version=SCHEMA["version"],
            rows=[{"team_name": name} for name in names],
            complete_list_confirmed=True,
        ),
    )
    assert batch["errors"]
    with pytest.raises(ApiProblem):
        commit_import(
            round.pk, verifier, action(batch_id=batch["batch_id"], evidence_confirmed=True)
        )
    assert GreenCardRevision.objects.count() == 0


def test_complete_list_required_and_card_correction_is_replacement_not_credit(cards):
    round, teams, maker, _ = cards
    with pytest.raises(ApiProblem, match="complete"):
        validate_import(
            round.pk,
            maker,
            action(schema_version=SCHEMA["version"], rows=[{"team_name": teams[0].code}]),
        )
    intake(cards, [teams[0].code])
    intake(cards, [teams[1].code])
    assert GreenCardRevision.objects.count() == 6
    effective = {r.team_id: r for r in GreenCardRevision.objects.order_by("pk")}
    assert not effective[teams[0].pk].received and effective[teams[1].pk].received
    assert all(r.supersedes_id for r in effective.values())


def test_signed_recovery_restores_original_green_card_evidence(cards):
    round, teams, maker, verifier = cards
    intake(cards, [teams[0].code])
    expected = list(GreenCardRevision.objects.values_list("pk", "team_id", "received"))
    bundle = make_bundle(round)
    GreenCardRevision.objects.all()._raw_delete("default")
    recover(round, maker, verifier, bundle)
    assert list(GreenCardRevision.objects.values_list("pk", "team_id", "received")) == expected
