import runpy
from pathlib import Path

import pytest
from django.contrib.auth import get_user_model
from django.utils import timezone

from competition.demo import demo_rules
from competition.green_cards import SCHEMA
from competition.models import AuditEvent, GreenCardRevision, ResultSnapshot, Round, Team
from competition.rules import approve_rules, mark_ready

pytestmark = pytest.mark.django_db
publish = runpy.run_path(
    str(Path(__file__).resolve().parents[2] / "tools" / "publish_round4_finalists.py")
)["publish"]


@pytest.fixture
def ready():
    users = get_user_model().objects
    maker = users.create_superuser(username="script-maker", password=None)
    verifier = users.create_superuser(username="script-verifier", password=None)
    teams = [
        Team.objects.create(
            code=f"SYN-{i}",
            name=f"Synthetic {i}",
            member_count=4,
            user=users.create_user(username=f"script-team-{i}"),
        )
        for i in range(6)
    ]
    previous = Round.objects.create(number=3, state="FINALIZED")
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
        delivery_mode="EXTERNAL",
        active_budget_ms=3600000,
        advancement_count=5,
        rules_version="synthetic-card-v2",
        owners={
            **{
                k: maker.pk
                for k in ["technical_lead", "content_lead", "operations_lead", "adjudicator"]
            },
            "verifier": verifier.pk,
        },
        rules={
            **demo_rules(4),
            "score_schema": dict(SCHEMA),
            "ranking_policy": "green_card_qualification",
        },
    )
    approve_rules(round.pk, verifier)
    mark_ready(round.pk, maker)
    return round, teams, maker, verifier


@pytest.mark.parametrize("legacy", [True, False])
def test_immediate_publication_compatible_with_deployed_service_and_retries(ready, legacy):
    round, teams, maker, verifier = ready
    codes = [t.code for t in teams[:5]]
    kwargs = {
        "reviewed": True,
        "dry_run": False,
        "maker_name": maker.username,
        "verifier_name": verifier.username,
        "force_legacy": legacy,
    }
    result = publish(codes, **kwargs)
    assert set(result["qualifier_codes"]) == set(codes)
    snapshots = list(ResultSnapshot.objects.filter(round=round).order_by("revision"))
    assert [s.status for s in snapshots] == ["PROVISIONAL", "FINAL"]
    assert snapshots[0].appeal_deadline > snapshots[1].published_at
    assert GreenCardRevision.objects.filter(round=round, received=True).count() == 5
    assert GreenCardRevision.objects.filter(round=round, received=False).count() == 1
    assert AuditEvent.objects.filter(action="round4_appeal_override").count() == 1
    assert publish(codes, **kwargs)["already_final"] is True


def test_dry_run_rolls_back_every_publication(ready):
    round, teams, maker, verifier = ready
    publish(
        [t.code for t in teams[:5]],
        reviewed=True,
        dry_run=True,
        maker_name=maker.username,
        verifier_name=verifier.username,
        force_legacy=True,
    )
    round.refresh_from_db()
    assert round.state == "READY"
    assert not GreenCardRevision.objects.exists()
    assert not ResultSnapshot.objects.filter(round=round).exists()
