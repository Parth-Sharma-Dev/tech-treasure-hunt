from datetime import timedelta
from unittest.mock import patch

import pytest
from django.utils import timezone
from test_buzzer import action
from test_buzzer import buzzer as _buzzer
from test_buzzer_scores import final as _final
from test_buzzer_scores import played, publish
from test_later_round_recovery import recover

from competition.api import ApiProblem
from competition.buzzer_content import stages_for
from competition.buzzer_scores import carry_over, commit_import, validate_import
from competition.buzzer_scoring_rules import CONTRACT
from competition.evidence import make_bundle
from competition.models import BuzzerScoreRevision, BuzzerWindow, ResultSnapshot
from competition.results import build_preview

pytestmark = pytest.mark.django_db
buzzer = _buzzer
final = _final


@pytest.fixture
def weighted(final):
    round = final[0]
    round.rules = {**round.rules, "score_schema": dict(CONTRACT)}
    round.save()
    return final


def intake(weighted, rows):
    round = weighted[0]
    batch = validate_import(round.pk, weighted[3], action(schema_version="round5-v2", rows=rows))
    assert batch["errors"] == []
    commit_import(
        round.pk, weighted[4], action(batch_id=batch["batch_id"], evidence_confirmed=True)
    )
    round.refresh_from_db()


def test_weighted_stages_total_thirty_and_only_prior_three_rounds_carry(weighted):
    rows = played(weighted, count=25)
    stage4 = set(BuzzerWindow.objects.filter(question__stage=4).values_list("pk", flat=True))
    for row in rows:
        if row["window_id"] in stage4:
            row["reveal_step"] = "2"
    intake(weighted, rows)
    preview = build_preview(weighted[0], timezone.now())
    assert preview["configuration_errors"] == [] and preview["evidence_gaps"] == []
    assert preview["round5_max_score"] == 30
    assert preview["entries"][0]["stage_scores"] == {"1": 5, "2": 5, "3": 5, "4": 5, "5": 10}
    assert preview["entries"][0]["carry_over_score"] == 12
    assert preview["entries"][0]["score"] == 42
    stages = stages_for(weighted[0])
    assert [s["title"] for s in stages][2:] == [
        "Image abnormalities",
        "Progressive image guessing",
        "Word encoding",
    ]
    publish(weighted)
    latest = ResultSnapshot.objects.filter(round=weighted[0]).latest("revision")
    with patch(
        "competition.results.database_now",
        return_value=latest.appeal_deadline + timedelta(seconds=1),
    ):
        publish(weighted, "FINAL")
    award = ResultSnapshot.objects.filter(round=weighted[0]).latest("revision")
    assert award.metadata["winner_codes"] == [weighted[2][0].code] and award.qualifier_codes == []


def test_word_encoding_rejects_image_reveal_steps_and_legacy_source_contract(weighted):
    rows = played(weighted, count=5)
    with pytest.raises(ApiProblem, match="round5-v2"):
        validate_import(weighted[0].pk, weighted[3], action(schema_version="round5-v1", rows=rows))
    encoding = BuzzerWindow.objects.get(question__stage=5)
    for row in rows:
        if row["window_id"] == encoding.pk:
            row["reveal_step"] = "1"
    batch = validate_import(
        weighted[0].pk, weighted[3], action(schema_version="round5-v2", rows=rows)
    )
    assert batch["errors"] and not BuzzerScoreRevision.objects.exists()


def test_raw_wayground_points_carry_without_presenting_storage_bound_as_maximum(weighted):
    snapshot = ResultSnapshot.objects.filter(round__number=2).latest("revision")
    old_score = snapshot.ranked_entries[0]["score"]
    entries = [dict(entry, score=7000, max_score=9999999.999) for entry in snapshot.ranked_entries]
    ResultSnapshot.objects.filter(pk=snapshot.pk).update(
        ranked_entries=entries, metadata={"ranking_kind": "WAYGROUND_RAW"}
    )
    intake(weighted, played(weighted, count=25))
    preview = build_preview(weighted[0], timezone.now())
    assert not preview["configuration_errors"] and not preview["evidence_gaps"]
    entry = preview["entries"][0]
    assert entry["score_basis"] == "CUMULATIVE_RAW"
    assert entry["carry_over_score"] == 12 - old_score + 7000
    assert entry["score"] == 42 - old_score + 7000


def test_zero_point_green_card_snapshot_is_valid_qualification_but_not_carried_score(weighted):
    snapshot = ResultSnapshot.objects.filter(round__number=4).latest("revision")
    entries = [
        dict(entry, score=0, max_score=0, green_card=True) for entry in snapshot.ranked_entries
    ]
    ResultSnapshot.objects.filter(pk=snapshot.pk).update(
        ranked_entries=entries, metadata={"ranking_kind": "GREEN_CARDS"}
    )
    codes, totals, _, errors = carry_over(weighted[0])
    assert not errors and all(totals[code]["score"] == 12 for code in codes)
    entries[0]["green_card"] = False
    ResultSnapshot.objects.filter(pk=snapshot.pk).update(ranked_entries=entries)
    assert carry_over(weighted[0])[3]


def test_signed_recovery_reproduces_weighted_thirty_mark_credit(weighted):
    intake(weighted, played(weighted, count=25))
    round = weighted[0]
    expected = build_preview(round, timezone.now())["entries"]
    bundle = make_bundle(round)
    BuzzerScoreRevision.objects.all()._raw_delete("default")
    recover(round, weighted[3], weighted[4], bundle)
    round.refresh_from_db()
    assert build_preview(round, timezone.now())["entries"] == expected


def test_voiding_word_encoding_removes_two_marks_from_its_effective_maximum(weighted):
    rows = played(weighted, count=5)
    encoding = BuzzerWindow.objects.get(question__stage=5)
    for row in rows:
        if row["window_id"] == encoding.pk:
            row["verdict"] = "VOID"
            row["adjudication_reference"] = "Synthetic encoding fault"
    intake(weighted, rows)
    preview = build_preview(weighted[0], timezone.now())
    assert preview["round5_max_score"] == 4
    assert preview["entries"][0]["round5_score"] == 4
