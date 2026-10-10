import uuid

import pytest
from test_gameplay import game as _game
from test_gameplay import post

from competition.answers import NEW_FORMAT, answer_digest
from competition.models import Completion, Mission, Round, SubmissionDecision

pytestmark = pytest.mark.django_db
game = _game


def six(game):
    round, missions, _, _, client = game
    rules = {**round.rules_snapshot["rules"], "answer_format": NEW_FORMAT}
    Round.objects.filter(pk=round.pk).update(rules_snapshot={"rules": rules})
    for mission in missions:
        Mission.objects.filter(pk=mission.pk).update(
            answer_verifiers=[
                {"version": "six-v1", "digest": answer_digest(mission.pk, "six-v1", "AB0042")}
            ]
        )
    round.refresh_from_db()
    return round, missions, client


def test_six_character_mixed_case_code_and_replay_preserve_one_credit(game):
    _, missions, client = six(game)
    mission = missions[0]
    assert client.get(f"/api/missions/{mission.token}").json()["answer_format"] == NEW_FORMAT
    assert post(client, "/api/missions/open", {"token": mission.token}).status_code == 200
    key = uuid.uuid4()
    first = post(client, f"/api/missions/{mission.token}/submit", {"answer": "ab0042"}, key)
    assert first.status_code == 200 and first.json()["outcome"] == "accepted"
    again = post(client, f"/api/missions/{mission.token}/submit", {"answer": "AB0042"}, key).json()
    assert {k: v for k, v in again.items() if k != "request_id"} == {
        k: v for k, v in first.json().items() if k != "request_id"
    }
    assert Completion.objects.count() == 1 and SubmissionDecision.objects.count() == 1


def test_six_code_rejects_old_lengths_unicode_and_punctuation_without_evidence(game):
    _, missions, client = six(game)
    for answer in ["0042", "AB042", "ABC0042", "AB-042", "ＡＢ0042", "AB0042 ", "AB0042\n"]:
        result = post(
            client, f"/api/missions/{missions[0].token}/submit", {"answer": answer}, uuid.uuid4()
        )
        assert result.status_code == 400 and result.json()["error"]["code"] == "invalid_format"
    assert SubmissionDecision.objects.count() == 0


def test_six_character_practice_is_case_insensitive_and_never_scores(game):
    _, missions, client = six(game)
    Mission.objects.filter(pk=missions[0].pk).update(is_practice=True)
    assert client.get("/api/practice").json()["answer_format"] == NEW_FORMAT
    result = post(client, "/api/practice/submit", {"answer": "ab0042"})
    assert result.status_code == 200 and result.json()["outcome"] == "accepted"
    assert result.json()["points_awarded"] == 0 and Completion.objects.count() == 0
