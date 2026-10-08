import uuid
from datetime import timedelta

import pytest
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import Client
from django.utils import timezone

from competition.api import ApiProblem
from competition.clock import control_round, database_now
from competition.demo import demo_rules
from competition.external_scores import commit_import, validate_import
from competition.external_voids import question_void
from competition.faculty import publish_faculty
from competition.models import (
    FacultyProfile,
    ResultSnapshot,
    Round,
    ScoreRevision,
    Team,
)
from competition.portal import overview
from competition.results import approve_result, build_preview, propose_result
from competition.rules import approve_rules, mark_ready, readiness_errors

pytestmark = pytest.mark.django_db


def action(**data):
    return {"action_id": str(uuid.uuid4()), "reason": "Synthetic evidence review", **data}


@pytest.fixture
def external():
    users = get_user_model()
    maker = users.objects.create_superuser(username="external-maker", password=None)
    verifier = users.objects.create_superuser(username="external-reviewer", password=None)
    teams = [
        Team.objects.create(
            code=f"EXT-{i}",
            name=f"External {i}",
            is_demo=True,
            member_count=3,
            user=users.objects.create_user(username=f"external-{i}"),
        )
        for i in range(3)
    ]
    previous = Round.objects.create(
        number=1, title="Isolated qualification fixture", is_demo=True, state="FINALIZED"
    )
    ResultSnapshot.objects.create(
        round=previous,
        revision=1,
        status="FINAL",
        qualifier_codes=[team.code for team in teams],
        maker=maker,
        approver=verifier,
        published_at=timezone.now(),
    )
    round = Round.objects.create(
        number=2,
        title="Synthetic paper quiz",
        is_demo=True,
        delivery_mode="EXTERNAL",
        active_budget_ms=60000,
        advancement_count=1,
        rules_version="external-v1",
        rules=demo_rules(2),
        owners={
            **{
                key: maker.pk
                for key in ["technical_lead", "content_lead", "operations_lead", "adjudicator"]
            },
            "verifier": verifier.pk,
        },
    )
    return round, teams, maker, verifier


def end(fixture):
    round, _, maker, verifier = fixture
    approve_rules(round.pk, verifier)
    mark_ready(round.pk, maker)
    for operation in ["open_lobby", "start", "end"]:
        round.refresh_from_db()
        control_round(
            round.pk, maker, action(action=operation, expected_version=round.control_version)
        )
    round.refresh_from_db()


def rows(teams):
    return [
        {
            "team_code": team.code,
            "correct_question_ids": ["Q01", "Q02"] if i == 0 else ["Q01"],
            "official_finish_active_ms": 1000 + i * 100,
            "source_reference": f"Synthetic sheet {i}",
        }
        for i, team in enumerate(teams)
    ]


def intake(fixture, source=None):
    round, teams, maker, verifier = fixture
    batch = validate_import(
        round.pk,
        maker,
        action(
            schema_version=f"round{round.number}-v1",
            rows=source if source is not None else rows(teams),
        ),
    )
    commit_import(round.pk, verifier, action(batch_id=batch["batch_id"], evidence_confirmed=True))
    round.refresh_from_db()
    return batch


def test_external_dry_run_independent_atomic_and_idempotent(external):
    end(external)
    round, teams, maker, verifier = external
    request = action(schema_version="round2-v1", rows=rows(teams))
    preview = validate_import(round.pk, maker, request)
    assert not ScoreRevision.objects.exists()
    assert validate_import(round.pk, maker, request) == preview
    review = action(batch_id=preview["batch_id"], evidence_confirmed=True)
    with pytest.raises(ApiProblem, match="different verifier"):
        commit_import(round.pk, maker, review)
    response = commit_import(round.pk, verifier, review)
    assert commit_import(round.pk, verifier, review) == response
    assert ScoreRevision.objects.count() == 3
    assert not build_preview(Round.objects.get(pk=round.pk), database_now())["evidence_gaps"]


@pytest.mark.parametrize(
    "bad",
    [
        {"correct_question_ids": ["Q01", "Q01"]},
        {"correct_question_ids": ["unknown"]},
        {"correct_question_ids": True},
        {"official_finish_active_ms": True},
        {"official_finish_active_ms": "NaN"},
        {"official_finish_active_ms": -1},
        {"official_finish_active_ms": 60001},
        {"source_reference": ""},
        {"team_code": "missing"},
    ],
)
def test_invalid_source_batch_cannot_commit_any_row(external, bad):
    end(external)
    round, teams, maker, verifier = external
    source = rows(teams)
    source[1].update(bad)
    preview = validate_import(round.pk, maker, action(schema_version="round2-v1", rows=source))
    assert preview["errors"]
    with pytest.raises(ApiProblem, match="entire batch"):
        commit_import(
            round.pk, verifier, action(batch_id=preview["batch_id"], evidence_confirmed=True)
        )
    assert not ScoreRevision.objects.exists()


def test_corrections_append_and_invalidate_old_preview(external):
    end(external)
    round, teams, maker, verifier = external
    intake(external)
    source = rows(teams)
    source[0]["correct_question_ids"] = []
    pending = validate_import(round.pk, maker, action(schema_version="round2-v1", rows=source))
    teams[0].status = "WITHDRAWN"
    teams[0].save()
    with pytest.raises(ApiProblem, match="changed"):
        commit_import(
            round.pk, verifier, action(batch_id=pending["batch_id"], evidence_confirmed=True)
        )
    teams[0].status = "ACTIVE"
    teams[0].save()
    commit_import(round.pk, verifier, action(batch_id=pending["batch_id"], evidence_confirmed=True))
    assert ScoreRevision.objects.count() == 6
    assert ScoreRevision.objects.filter(supersedes__isnull=False).count() == 3
    assert (
        build_preview(Round.objects.get(pk=round.pk), database_now())["entries"][0]["team_code"]
        == teams[1].code
    )


def test_csv_headers_duplicates_and_unqualified_team(external):
    end(external)
    round, teams, maker, _ = external
    with pytest.raises(ApiProblem, match="Required columns"):
        validate_import(
            round.pk, maker, action(schema_version="round2-v1", csv="score,team_code\n1,EXT-0")
        )
    source = rows(teams)
    preview = validate_import(
        round.pk, maker, action(schema_version="round2-v1", rows=source + [source[0]])
    )
    assert any("Duplicate" in error["message"] for error in preview["errors"])
    teams[0].status = "DISQUALIFIED"
    teams[0].save()
    preview = validate_import(round.pk, maker, action(schema_version="round2-v1", rows=rows(teams)))
    assert any("not qualified" in error["message"] for error in preview["errors"])


def publish(round, maker, verifier, status="PROVISIONAL", **extra):
    round.refresh_from_db()
    preview = build_preview(round, database_now())
    proposal = propose_result(
        round.pk,
        maker,
        action(
            status=status,
            expected_version=round.control_version,
            evidence_digest=preview["evidence_digest"],
            evidence_confirmed=True,
            **extra,
        ),
    )
    return approve_result(
        round.pk, verifier, action(proposal_id=proposal["proposal_id"], evidence_confirmed=True)
    )


def test_question_void_preserves_source_and_restarts_appeals(external):
    end(external)
    round, teams, maker, verifier = external
    intake(external)
    publish(round, maker, verifier)
    proposal = question_void(
        round.pk,
        maker,
        action(operation="propose", question_id="Q02", source_reference="Fault report"),
    )
    with pytest.raises(ApiProblem, match="different reviewer"):
        question_void(
            round.pk,
            maker,
            action(
                operation="review", proposal_id=proposal["proposal_id"], evidence_confirmed=True
            ),
        )
    question_void(
        round.pk,
        verifier,
        action(operation="review", proposal_id=proposal["proposal_id"], evidence_confirmed=True),
    )
    round.refresh_from_db()
    preview = build_preview(round, database_now())
    assert preview["max_score"] == 29
    assert preview["entries"][0]["score"] == 1
    assert ScoreRevision.objects.get(team=teams[0]).score == 2
    assert any("revised provisional" in value for value in preview["finalization_blockers"])
    publish(round, maker, verifier)
    assert ResultSnapshot.objects.filter(round=round).count() == 2


def test_reviewed_round2_final_unlocks_round3(external):
    end(external)
    round, teams, maker, verifier = external
    intake(external)
    publish(round, maker, verifier)
    provisional = ResultSnapshot.objects.get(round=round)
    # Advance the service's authoritative observation time; never shorten an actual appeal.
    from unittest.mock import patch

    with patch(
        "competition.results.database_now",
        return_value=provisional.appeal_deadline + timedelta(seconds=1),
    ):
        round.refresh_from_db()
        preview = build_preview(round, provisional.appeal_deadline + timedelta(seconds=1))
        proposal = propose_result(
            round.pk,
            maker,
            action(
                status="FINAL",
                expected_version=round.control_version,
                evidence_digest=preview["evidence_digest"],
                evidence_confirmed=True,
            ),
        )
        approve_result(
            round.pk, verifier, action(proposal_id=proposal["proposal_id"], evidence_confirmed=True)
        )
    coding = Round.objects.create(
        number=3, title="Following coding", is_demo=True, delivery_mode="CODING", state="READY"
    )
    assert overview(teams[0], coding)["eligible"]
    assert not overview(teams[1], coding)["eligible"]


def test_faculty_publication_consent_and_draft_privacy(external):
    _, teams, maker, verifier = external
    faculty = FacultyProfile.objects.create(
        display_name="Synthetic faculty",
        role="Contest faculty",
        consent_reference="Test consent",
        is_demo=True,
        prepared_by=maker,
    )
    round = Round.objects.create(number=4, title="Interview", is_demo=True)
    assert not overview(teams[0], round)["faculty"]
    with pytest.raises(ValidationError, match="different verifier"):
        publish_faculty(faculty.pk, maker)
    publish_faculty(faculty.pk, verifier)
    faculty.display_name = "Unapproved draft"
    faculty.save()
    assert overview(teams[0], round)["faculty"][0]["display_name"] == "Synthetic faculty"
    assert "consent_reference" not in overview(teams[0], round)["faculty"][0]


def test_round4_panel_averages_and_source_marks(external):
    round, teams, maker, verifier = external
    Round.objects.filter(pk=round.pk).delete()
    previous = Round.objects.create(
        number=3, title="Coding qualification fixture", state="FINALIZED", is_demo=True
    )
    ResultSnapshot.objects.create(
        round=previous,
        revision=1,
        status="FINAL",
        qualifier_codes=[team.code for team in teams],
        maker=maker,
        approver=verifier,
        published_at=timezone.now(),
    )
    faculty = []
    for i in range(3):
        profile = FacultyProfile.objects.create(
            display_name=f"Synthetic faculty {i}",
            role="Contest faculty",
            consent_reference="Test consent",
            is_demo=True,
            prepared_by=maker,
        )
        publish_faculty(profile.pk, verifier)
        faculty.append(profile.pk)
    rules = {
        **demo_rules(4),
        "ranking_policy": "weighted_faculty_criteria",
        "qualification_tie_policy": "supervised_reserve_question",
        "score_schema": {"version": "round4-v1", "max_score": "100", "rounding": "half_up_3"},
        "faculty_panels": [
            {
                "label": "Synthetic panel",
                "faculty_ids": faculty,
                "slots": [
                    {
                        "team_code": team.code,
                        "start": (timezone.now() + timedelta(minutes=i * 10)).isoformat(),
                        "end": (timezone.now() + timedelta(minutes=i * 10 + 10)).isoformat(),
                    }
                    for i, team in enumerate(teams)
                ],
            }
        ],
    }
    interview = Round.objects.create(
        number=4,
        title="Synthetic interview",
        is_demo=True,
        delivery_mode="EXTERNAL",
        active_budget_ms=60000,
        advancement_count=1,
        rules_version="interview-v1",
        rules=rules,
        owners=round.owners,
    )
    fixture = interview, teams, maker, verifier
    end(fixture)
    source = [
        {
            "team_code": team.code,
            "faculty_id": identity,
            "technical": "8",
            "problem_solving": "7",
            "communication": "6",
            "coordination": str(5 - i),
            "source_reference": f"Sheet {team.code}-{identity}",
        }
        for i, team in enumerate(teams)
        for identity in faculty
    ]
    invalid = validate_import(
        interview.pk, maker, action(schema_version="round4-v1", rows=source[:-1])
    )
    assert invalid["errors"]
    commit_import(interview.pk, verifier, action(batch_id=invalid["batch_id"], reject=True))
    intake(fixture, source)
    preview = build_preview(Round.objects.get(pk=interview.pk), database_now())
    assert not preview["evidence_gaps"]
    assert preview["entries"][0]["score"] == 69
    revision = ScoreRevision.objects.get(team=teams[0])
    assert len(revision.tie_metrics["faculty_marks"]) == 3
    assert "faculty_marks" not in str(preview["entries"])
    publish(interview, maker, verifier)


def test_external_endpoints_reject_participants(external):
    end(external)
    round, teams, _, _ = external
    client = Client()
    client.force_login(teams[0].user)
    assert client.get(f"/api/staff/rounds/{round.pk}/imports").status_code == 403
    assert (
        client.post(
            f"/api/staff/rounds/{round.pk}/imports/validate",
            action(),
            content_type="application/json",
        ).status_code
        == 403
    )


def test_real_round2_requires_manual_contract(external):
    round = external[0]
    round.is_demo = False
    assert any("30 questions" in error for error in readiness_errors(round))


def test_original_source_batch_is_immutable_and_extra_csv_cells_are_rejected(external):
    from competition.models import ImportBatch

    end(external)
    round, _, maker, _ = external
    intake(external)
    batch = ImportBatch.objects.get()
    batch.source_rows = []
    with pytest.raises(ValidationError, match="cannot be rewritten"):
        batch.save()
    with pytest.raises(ApiProblem, match="extra CSV cells"):
        validate_import(
            round.pk,
            maker,
            action(
                schema_version="round2-v1",
                csv="team_code,correct_question_ids,official_finish_active_ms,source_reference\nEXT-0,Q01,1,Ref,Extra",
            ),
        )


def test_external_cutoff_tie_needs_common_reserve_evidence(external):
    from unittest.mock import patch

    end(external)
    round, teams, maker, verifier = external
    source = rows(teams)
    for item in source:
        item["correct_question_ids"] = ["Q01"]
        item["official_finish_active_ms"] = 1000
    intake(external, source)
    publish(round, maker, verifier)
    provisional = ResultSnapshot.objects.get(round=round)
    future = provisional.appeal_deadline + timedelta(seconds=1)
    with patch("competition.results.database_now", return_value=future):
        round.refresh_from_db()
        preview = build_preview(round, future)
        data = action(
            status="FINAL",
            expected_version=round.control_version,
            evidence_digest=preview["evidence_digest"],
            evidence_confirmed=True,
        )
        with pytest.raises(ApiProblem, match="tied teams"):
            propose_result(round.pk, maker, data)
        proposal = propose_result(
            round.pk,
            maker,
            {
                **data,
                "tie_order": [team.code for team in reversed(teams)],
                "tie_evidence": ["Private common reserve report"],
                "tie_reason": "Common sealed reserve question reviewed",
            },
        )
        approve_result(
            round.pk, verifier, action(proposal_id=proposal["proposal_id"], evidence_confirmed=True)
        )
    assert ResultSnapshot.objects.filter(round=round).latest("revision").qualifier_codes == [
        teams[2].code
    ]


@pytest.mark.parametrize("value", ["NaN", "Infinity", "-0.01", "10.001", "1.0001", True, {}, None])
def test_faculty_marks_require_finite_in_range_precision(value):
    from decimal import Decimal

    from competition.external_scores import decimal_value

    with pytest.raises(ValueError):
        decimal_value(value, Decimal(10))
