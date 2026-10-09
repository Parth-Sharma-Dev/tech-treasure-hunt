"""Signed checkpoints cover original sources, not just the projected points."""

import pytest
from django.utils import timezone
from test_coding import coding as _coding
from test_external_scores import end, intake
from test_external_scores import external as _external

from competition.evidence import compare_bundle, evidence_page, make_bundle, read_bundle
from competition.models import CodingRevision, FacultyProfile, RosterProposal, ScoreRevision
from competition.results import digest

pytestmark = pytest.mark.django_db
coding = _coding
external = _external


def test_coding_checkpoint_includes_private_tasks_and_missing_saved_source(coding):
    round, tasks, teams, maker, _ = coding
    round.state = "ENDED"
    round.save()
    import uuid

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
