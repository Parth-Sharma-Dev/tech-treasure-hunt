"""Signed checkpoints cover original sources, not just the projected points."""

import uuid

import pytest
from django.utils import timezone
from test_coding import coding as _coding
from test_coding import ended_bundle, grade_data
from test_external_scores import end, intake
from test_external_scores import external as _external

from competition.api import ApiProblem
from competition.coding_results import approve_judgment, propose_judgment
from competition.evidence import (
    EXPORT_SIGNER,
    approve_recovery,
    compare_bundle,
    evidence_page,
    export_objects,
    inventory,
    make_bundle,
    propose_recovery,
    read_bundle,
)
from competition.models import (
    CodingJudgment,
    CodingJudgmentProposal,
    CodingRevision,
    CodingSubmission,
    CodingWorkstation,
    FacultyProfile,
    Incident,
    RosterProposal,
    ScoreRevision,
    TeamSession,
)
from competition.results import build_preview, digest

pytestmark = pytest.mark.django_db
coding = _coding
external = _external


def test_coding_checkpoint_includes_private_tasks_and_missing_saved_source(coding):
    round, tasks, teams, maker, _ = coding
    round.state = "ENDED"
    round.save()
    saved = CodingRevision.objects.create(
        round=round,
        task=tasks[0],
        team=teams[0],
        action_id=uuid.uuid4(),
        revision=1,
        language="TEXT",
        body="retained draft",
        source_hash=digest("retained draft"),
        admitted_at=timezone.now(),
        active_elapsed_ms=100,
    )
    payload = read_bundle(make_bundle(round)["signed_bundle"], round)
    assert payload["format"] == "round-evidence-v2"
    assert (
        len([item for item in payload["objects"] if item["model"] == "competition.codingtask"]) == 5
    )
    assert "private correct answer" in str(payload["objects"])
    CodingRevision.objects.filter(pk=saved.pk)._raw_delete("default")
    assert compare_bundle(round, payload)["missing"] == [f"competition.codingrevision:{saved.pk}"]
    page = evidence_page(round.pk, maker, "codingtask", limit=1)
    assert len(page["objects"]) == 1 and page["next_cursor"]


def test_external_checkpoint_retains_source_batches_faculty_and_roster(external):
    round, _, maker, _ = external
    end(external)
    intake(external)
    faculty = FacultyProfile.objects.create(
        display_name="PLACEHOLDER faculty",
        role="Pending organizer assignment",
        is_demo=True,
        consent_reference="PLACEHOLDER — not approved",
        prepared_by=maker,
    )
    FacultyProfile.objects.create(
        display_name="Other cohort",
        role="Private",
        is_demo=False,
        consent_reference="private",
    )
    roster = RosterProposal.objects.create(
        maker=maker,
        payload={"is_demo": True, "rows": []},
        evidence_digest=digest([]),
        reason="fixture",
    )
    payload = read_bundle(make_bundle(round)["signed_bundle"], round)
    models = {item["model"] for item in payload["objects"]}
    assert {
        "competition.importbatch",
        "competition.scorerevision",
        "competition.rosterproposal",
    } <= models
    assert [
        item["pk"] for item in payload["objects"] if item["model"] == "competition.facultyprofile"
    ] == [faculty.pk]
    assert f"competition.rosterproposal:{roster.pk}" in payload["inventory"]
    assert "session_key" not in str(payload)
    source = ScoreRevision.objects.first()
    ScoreRevision.objects.filter(pk=source.pk)._raw_delete("default")
    assert f"competition.scorerevision:{source.pk}" in compare_bundle(round, payload)["missing"]


def recover(round, maker, reviewer, bundle):
    proposed = propose_recovery(
        round.pk,
        maker,
        {
            "action_id": str(uuid.uuid4()),
            "expected_version": round.control_version,
            "reason": "Restore retained synthetic evidence",
            "evidence_refs": ["private-checkpoint"],
            "signed_bundle": bundle["signed_bundle"],
        },
    )
    review = {
        "action_id": str(uuid.uuid4()),
        "proposal_id": proposed["recovery_proposal_id"],
        "reason": "Independently checked source coverage",
        "evidence_confirmed": True,
    }
    result = approve_recovery(round.pk, reviewer, review)
    assert approve_recovery(round.pk, reviewer, review) == result
    return result


def judged(coding):
    submission = ended_bundle(coding)
    round, _, _, maker, reviewer = coding
    proposal = propose_judgment(round.pk, maker, grade_data(coding, submission))
    approve_judgment(
        round.pk,
        reviewer,
        {
            "action_id": str(uuid.uuid4()),
            "proposal_id": proposal["judgment_proposal_id"],
            "reason": "Synthetic independent grade review",
            "evidence_confirmed": True,
        },
    )
    round.refresh_from_db()
    assert build_preview(round, timezone.now())["evidence_gaps"] == []
    return submission


def test_recovery_restores_missing_coding_sources_final_and_judging_with_revoked_station(coding):
    judged(coding)
    round, _, _, maker, reviewer = coding
    original = export_objects(round)
    bundle = make_bundle(round)
    session_key = TeamSession.objects.get().session_key
    for model in [
        CodingJudgment,
        CodingJudgmentProposal,
        CodingSubmission,
        CodingRevision,
        CodingWorkstation,
        TeamSession,
    ]:
        model.objects.all()._raw_delete("default")
    assert recover(round, maker, reviewer, bundle)["reconciled"]
    session = TeamSession.objects.get()
    assert session.revoked_at and session.session_key != session_key
    round.refresh_from_db()
    assert build_preview(round, timezone.now())["evidence_gaps"] == []
    restored = {f"{item['model']}:{item['pk']}": item for item in export_objects(round)}
    for item in original:
        if item["model"].startswith("competition.coding"):
            assert restored[f"{item['model']}:{item['pk']}"] == item


def test_external_recovery_restores_scores_once_and_preserves_withdrawal(external):
    end(external)
    intake(external)
    round, teams, maker, reviewer = external
    bundle = make_bundle(round)
    expected = list(ScoreRevision.objects.values_list("pk", "score"))
    ScoreRevision.objects.all()._raw_delete("default")
    teams[0].status = "WITHDRAWN"
    teams[0].save(update_fields=["status"])
    recover(round, maker, reviewer, bundle)
    assert list(ScoreRevision.objects.values_list("pk", "score")) == expected
    teams[0].refresh_from_db()
    assert teams[0].status == "WITHDRAWN"


def test_recovery_reapplies_checkpoint_disqualification_without_reactivating_access(external):
    end(external)
    intake(external)
    round, teams, maker, reviewer = external
    teams[0].status = "DISQUALIFIED"
    teams[0].save(update_fields=["status"])
    bundle = make_bundle(round)
    teams[0].status = "ACTIVE"
    teams[0].save(update_fields=["status"])
    recover(round, maker, reviewer, bundle)
    teams[0].refresh_from_db()
    assert teams[0].status == "DISQUALIFIED"


def test_recovery_blocks_changed_coding_source_and_keeps_incident_open(coding):
    judged(coding)
    round, _, _, maker, reviewer = coding
    bundle = make_bundle(round)
    CodingRevision.objects.filter(pk=CodingRevision.objects.first().pk).update(body="conflict")
    with pytest.raises(ApiProblem, match="Immutable evidence differs"):
        recover(round, maker, reviewer, bundle)
    assert Incident.objects.filter(category="RECOVERY", closed_at__isnull=True).exists()


def test_recovery_blocks_roster_identity_drift(external):
    end(external)
    intake(external)
    round, teams, maker, reviewer = external
    bundle = make_bundle(round)
    teams[0].leader_name = "Different identity"
    teams[0].save(update_fields=["leader_name"])
    with pytest.raises(ApiProblem, match="Roster/account identities differ"):
        recover(round, maker, reviewer, bundle)


def test_old_round1_checkpoint_remains_readable_but_cannot_certify_round3(coding):
    round = coding[0]
    round.state = "ENDED"
    round.save()
    payload = read_bundle(make_bundle(round)["signed_bundle"], round)
    payload["format"] = "round-evidence-v1"
    payload["objects"] = export_objects(round, extended=False)
    payload["inventory"] = inventory(payload["objects"])
    with pytest.raises(ApiProblem, match="different rules/attempt"):
        read_bundle(EXPORT_SIGNER.sign_object(payload), round)


def test_new_session_between_proposal_and_review_is_revoked(external):
    end(external)
    intake(external)
    round, teams, maker, reviewer = external
    bundle = make_bundle(round)
    proposed = propose_recovery(
        round.pk,
        maker,
        {
            "action_id": str(uuid.uuid4()),
            "expected_version": round.control_version,
            "reason": "Recovery session race",
            "evidence_refs": ["checkpoint"],
            "signed_bundle": bundle["signed_bundle"],
        },
    )
    session = TeamSession.objects.create(
        team=teams[0],
        session_key="new-cookie-after-proposal",
        session_version=2,
        last_seen_at=timezone.now(),
        expires_at=timezone.now(),
    )
    approve_recovery(
        round.pk,
        reviewer,
        {
            "action_id": str(uuid.uuid4()),
            "proposal_id": proposed["recovery_proposal_id"],
            "reason": "Review session revocation",
            "evidence_confirmed": True,
        },
    )
    session.refresh_from_db()
    assert session.revoked_at


def test_recovery_refuses_to_interrupt_another_live_round(external):
    from competition.models import Round

    end(external)
    round, _, maker, reviewer = external
    bundle = make_bundle(round)
    Round.objects.create(number=3, title="Other live round", is_demo=True, state="LIVE")
    with pytest.raises(ApiProblem, match="Stop all cohort play"):
        recover(round, maker, reviewer, bundle)
    assert not Incident.objects.filter(category="RECOVERY").exists()


def test_recovery_restores_reviewed_question_void_and_original_batch(external):
    from test_external_scores import action

    from competition.external_voids import question_void
    from competition.models import ExternalQuestionVoid, ExternalVoidProposal, ImportBatch

    end(external)
    intake(external)
    round, _, maker, reviewer = external
    proposed = question_void(
        round.pk,
        maker,
        action(operation="propose", question_id="Q02", source_reference="Synthetic fault report"),
    )
    question_void(
        round.pk,
        reviewer,
        action(operation="review", proposal_id=proposed["proposal_id"], evidence_confirmed=True),
    )
    round.refresh_from_db()
    bundle = make_bundle(round)
    for model in [ExternalQuestionVoid, ExternalVoidProposal, ScoreRevision, ImportBatch]:
        model.objects.all()._raw_delete("default")
    recover(round, maker, reviewer, bundle)
    round.refresh_from_db()
    preview = build_preview(round, timezone.now())
    assert preview["evidence_gaps"] == [] and preview["max_score"] == 29
    assert ImportBatch.objects.count() == 1 and ExternalQuestionVoid.objects.count() == 1


def test_recovery_cannot_close_a_checkpoint_missing_lab_judging(coding):
    ended_bundle(coding)
    round, _, _, maker, reviewer = coding
    bundle = make_bundle(round)
    with pytest.raises(ApiProblem, match="reviewed lab judgment"):
        recover(round, maker, reviewer, bundle)
    assert Incident.objects.filter(category="RECOVERY", closed_at__isnull=True).exists()


def test_round4_recovery_restores_faculty_panels_original_marks_and_roster_evidence(external):
    from datetime import timedelta

    from competition.demo import demo_rules
    from competition.faculty import publish_faculty
    from competition.models import ImportBatch, ResultSnapshot, Round

    quiz, teams, maker, reviewer = external
    previous = Round.objects.create(
        number=3, title="Qualifying fixture", is_demo=True, state="FINALIZED"
    )
    ResultSnapshot.objects.create(
        round=previous,
        revision=1,
        status="FINAL",
        qualifier_codes=[team.code for team in teams],
        maker=maker,
        approver=reviewer,
        published_at=timezone.now(),
    )
    profiles = []
    for index in range(3):
        profile = FacultyProfile.objects.create(
            display_name=f"Synthetic faculty {index}",
            role="Contest faculty",
            is_demo=True,
            consent_reference="Synthetic consent",
            prepared_by=maker,
        )
        publish_faculty(profile.pk, reviewer)
        profiles.append(profile.pk)
    now = timezone.now()
    panels = [
        {
            "label": "Synthetic panel",
            "faculty_ids": profiles,
            "slots": [
                {
                    "team_code": team.code,
                    "start": (now + timedelta(minutes=index * 10)).isoformat(),
                    "end": (now + timedelta(minutes=index * 10 + 10)).isoformat(),
                }
                for index, team in enumerate(teams)
            ],
        }
    ]
    round = Round.objects.create(
        number=4,
        title="Synthetic interview recovery",
        is_demo=True,
        delivery_mode="EXTERNAL",
        active_budget_ms=60000,
        advancement_count=1,
        rules_version="interview-v1",
        owners=quiz.owners,
        rules={
            **demo_rules(4),
            "ranking_policy": "weighted_faculty_criteria",
            "qualification_tie_policy": "supervised_reserve_question",
            "score_schema": {"version": "round4-v1", "max_score": "100", "rounding": "half_up_3"},
            "faculty_panels": panels,
        },
    )
    fixture = round, teams, maker, reviewer
    end(fixture)
    intake(
        fixture,
        [
            {
                "team_code": team.code,
                "faculty_id": faculty,
                "technical": "8",
                "problem_solving": "7",
                "communication": "6",
                "coordination": "5",
                "source_reference": f"Synthetic sheet {team.code}-{faculty}",
            }
            for team in teams
            for faculty in profiles
        ],
    )
    roster = RosterProposal.objects.create(
        maker=maker,
        reason="Synthetic retained roster evidence",
        payload={"is_demo": True, "rows": []},
        evidence_digest=digest([]),
    )
    bundle = make_bundle(round)
    expected = read_bundle(bundle["signed_bundle"], round)["inventory"]
    for model in [ScoreRevision, ImportBatch, FacultyProfile, RosterProposal]:
        model.objects.all()._raw_delete("default")
    recover(round, maker, reviewer, bundle)
    round.refresh_from_db()
    preview = build_preview(round, timezone.now())
    assert preview["evidence_gaps"] == []
    assert round.rules_snapshot["rules"]["faculty_panels"] == panels
    assert RosterProposal.objects.filter(pk=roster.pk).exists()
    recovered = inventory(export_objects(round))
    assert all(
        recovered[key] == value
        for key, value in expected.items()
        if not key.startswith("competition.round:")
    )
