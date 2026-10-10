import base64
import io
import zipfile
from datetime import timedelta
from unittest.mock import patch
from xml.etree import ElementTree as ET

import pytest
from django.utils import timezone
from test_external_scores import action, end
from test_external_scores import external as _external
from test_later_round_recovery import recover

from competition.api import ApiProblem
from competition.evidence import make_bundle
from competition.external_scores import commit_import, validate_import
from competition.models import ResultSnapshot, ScoreRevision, WaygroundReport
from competition.results import approve_result, build_preview, propose_result
from competition.wayground import VERSION, schema, upload_report
from competition.wayground_workbook import read_workbook

pytestmark = pytest.mark.django_db
external = _external
HEADERS = [
    "Player Name",
    "Score",
    "Total Time Taken",
    "Correct",
    "Incorrect",
    "Total Questions Attempted",
    "Unattempted",
    "Yet to be graded",
    "Partially correct",
    "Ungraded",
]


def workbook(scores=("7000", "5390", "3180"), formula=False):
    ns = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
    sheet = ET.Element("worksheet", xmlns=ns)
    data = ET.SubElement(sheet, "sheetData")
    values = [HEADERS]
    for i, score in enumerate(scores):
        correct = (8, 6, 4)[i]
        values.append(
            [
                f"Player {i}",
                score,
                str((24, 25, 33)[i] / 86400),
                str(correct),
                str(8 - correct),
                "8",
                "0",
                "0",
                "0",
                "0",
            ]
        )
    for index, values_row in enumerate(values, 1):
        row = ET.SubElement(data, "row", r=str(index))
        for column, value in enumerate(values_row):
            cell = ET.SubElement(row, "c", r=f"{chr(65 + column)}{index}", t="inlineStr")
            ET.SubElement(ET.SubElement(cell, "is"), "t").text = value
            if formula and index == 2 and column == 1:
                ET.SubElement(cell, "f").text = "1+1"
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr(
            "xl/workbook.xml",
            f'<workbook xmlns="{ns}" '
            'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
            '<sheets><sheet name="Participant Data" sheetId="1" r:id="rId1"/></sheets></workbook>',
        )
        z.writestr(
            "xl/_rels/workbook.xml.rels",
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" Target="worksheets/sheet1.xml" Type="worksheet"/>'
            "</Relationships>",
        )
        z.writestr("xl/worksheets/sheet1.xml", ET.tostring(sheet))
    return out.getvalue()


@pytest.fixture
def way(external):
    round, teams, maker, verifier = external
    prior = ResultSnapshot.objects.filter(round__number=1).get()
    ResultSnapshot.objects.filter(pk=prior.pk).update(
        qualifier_codes=[teams[0].code, teams[1].code]
    )
    round.rules = {
        **round.rules,
        "score_schema": schema(8),
        "ranking_policy": "wayground_score_then_answer_time",
    }
    round.save()
    end(external)
    return external


def upload(way, raw=None):
    return upload_report(
        way[0].pk,
        way[2],
        action(
            filename="test-wayground.xlsx",
            content_base64=base64.b64encode(raw or workbook()).decode(),
        ),
    )


def mapping(way, report):
    return [
        {
            "report_id": report["report_id"],
            "source_row": i + 2,
            "team_code": way[1][i].code if i < 2 else "",
            "excluded": i == 2,
            "exclusion_reason": "Not a qualifying event team" if i == 2 else "",
        }
        for i in range(3)
    ]


def intake(way):
    report = upload(way)
    batch = validate_import(
        way[0].pk, way[2], action(schema_version=VERSION, rows=mapping(way, report))
    )
    assert not batch["errors"]
    with pytest.raises(ApiProblem, match="different verifier"):
        commit_import(
            way[0].pk, way[2], action(batch_id=batch["batch_id"], evidence_confirmed=True)
        )
    review = action(batch_id=batch["batch_id"], evidence_confirmed=True)
    result = commit_import(way[0].pk, way[3], review)
    assert commit_import(way[0].pk, way[3], review) == result
    way[0].refresh_from_db()
    return report, batch


def test_original_excel_values_and_day_fraction_conversion():
    metadata, players = read_workbook(workbook())
    assert metadata["question_count"] == 8
    assert [p["score"] for p in players] == ["7000", "5390", "3180"]
    assert [p["answer_time_ms"] for p in players] == [24000, 25000, 33000]
    with pytest.raises(ValueError, match="Formula"):
        read_workbook(workbook(formula=True))
    with pytest.raises(ValueError):
        read_workbook(b"not an xlsx")


def test_raw_platform_points_commit_and_publish_without_accuracy_normalization(way):
    _, batch = intake(way)
    assert [r["score"] for r in batch["preview"]] == ["7000", "5390"]
    preview = build_preview(way[0], timezone.now())
    assert preview["evidence_gaps"] == [] and preview["ranking_kind"] == "WAYGROUND_RAW"
    assert preview["entries"][0]["score"] == 7000
    assert preview["entries"][0]["reported_answer_time_ms"] == 24000
    for status in ["PROVISIONAL", "FINAL"]:
        latest = ResultSnapshot.objects.filter(round=way[0]).order_by("-revision").first()
        now = latest.appeal_deadline + timedelta(seconds=1) if latest else timezone.now()
        with patch("competition.results.database_now", return_value=now):
            preview = build_preview(way[0], now)
            proposed = propose_result(
                way[0].pk,
                way[2],
                action(
                    status=status,
                    expected_version=way[0].control_version,
                    evidence_digest=preview["evidence_digest"],
                    evidence_confirmed=True,
                ),
            )
            approve_result(
                way[0].pk,
                way[3],
                action(proposal_id=proposed["proposal_id"], evidence_confirmed=True),
            )
        way[0].refresh_from_db()
    assert ResultSnapshot.objects.filter(round=way[0]).latest("revision").qualifier_codes == [
        way[1][0].code
    ]


@pytest.mark.parametrize(
    "change", ["missing", "duplicate_team", "exclusion_without_reason", "injected_score"]
)
def test_incomplete_or_manipulated_mapping_does_not_commit(way, change):
    report = upload(way)
    rows = mapping(way, report)
    if change == "missing":
        rows.pop()
    elif change == "duplicate_team":
        rows[1]["team_code"] = rows[0]["team_code"]
    elif change == "exclusion_without_reason":
        rows[2]["exclusion_reason"] = ""
    else:
        rows[0]["score"] = "999999"
    batch = validate_import(way[0].pk, way[2], action(schema_version=VERSION, rows=rows))
    assert batch["errors"]
    with pytest.raises(ApiProblem):
        commit_import(
            way[0].pk, way[3], action(batch_id=batch["batch_id"], evidence_confirmed=True)
        )
    assert not ScoreRevision.objects.exists()


def test_equal_scores_use_lower_exported_duration_and_report_corrections_replace(way):
    raw = workbook(scores=("7000", "7000", "3180"))
    report = upload(way, raw)
    batch = validate_import(
        way[0].pk, way[2], action(schema_version=VERSION, rows=mapping(way, report))
    )
    commit_import(way[0].pk, way[3], action(batch_id=batch["batch_id"], evidence_confirmed=True))
    way[0].refresh_from_db()
    entries = build_preview(way[0], timezone.now())["entries"]
    assert entries[0]["team_code"] == way[1][0].code and entries[0]["rank"] == 1
    corrected = upload(way, workbook(scores=("6500", "7000", "3180")))
    batch = validate_import(
        way[0].pk, way[2], action(schema_version=VERSION, rows=mapping(way, corrected))
    )
    commit_import(way[0].pk, way[3], action(batch_id=batch["batch_id"], evidence_confirmed=True))
    assert (
        ScoreRevision.objects.count() == 4
        and ScoreRevision.objects.filter(supersedes__isnull=False).count() == 2
    )


def test_recovery_retains_original_workbook_and_reproduces_raw_points(way):
    intake(way)
    expected = list(ScoreRevision.objects.values_list("team_id", "score", "tie_metrics"))
    bundle = make_bundle(way[0])
    ScoreRevision.objects.all()._raw_delete("default")
    WaygroundReport.objects.all()._raw_delete("default")
    recover(way[0], way[2], way[3], bundle)
    assert list(ScoreRevision.objects.values_list("team_id", "score", "tie_metrics")) == expected
    assert (
        read_workbook(base64.b64decode(WaygroundReport.objects.get().content_base64))[0][
            "question_count"
        ]
        == 8
    )


def test_original_workbook_download_is_private_and_byte_exact(way):
    from django.test import Client

    raw = workbook()
    report = upload(way, raw)
    client = Client()
    client.force_login(way[1][0].user)
    url = f"/api/staff/rounds/{way[0].pk}/imports/wayground/{report['report_id']}"
    assert client.get(url).status_code == 403
    client.force_login(way[3])
    downloaded = client.get(url)
    assert downloaded.status_code == 200 and downloaded.content == raw
    assert downloaded["Cache-Control"] == "no-store"
    csrf = Client(enforce_csrf_checks=True)
    csrf.force_login(way[2])
    assert (
        csrf.post(
            f"/api/staff/rounds/{way[0].pk}/imports/wayground", {}, content_type="application/json"
        ).status_code
        == 403
    )


def test_damaged_original_report_blocks_source_commit(way):
    report = upload(way)
    batch = validate_import(
        way[0].pk, way[2], action(schema_version=VERSION, rows=mapping(way, report))
    )
    WaygroundReport.objects.filter(pk=report["report_id"]).update(
        content_base64=base64.b64encode(b"damaged").decode()
    )
    with pytest.raises(ApiProblem):
        commit_import(
            way[0].pk, way[3], action(batch_id=batch["batch_id"], evidence_confirmed=True)
        )
    assert not ScoreRevision.objects.exists()


@pytest.mark.django_db(transaction=True)
def test_real_browser_wayground_export_to_reviewed_publication(
    way, live_server, tmp_path, settings
):
    import os
    import shutil
    import subprocess
    from pathlib import Path

    if os.environ.get("TTH_BROWSER_INTEGRATION") != "1":
        pytest.skip("Opt-in: actual workbook upload and real browser/database journey.")
    settings.PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]
    for user in [way[2], way[3], way[1][0].user]:
        user.set_password("test-only")
        user.save(update_fields=["password"])
    path = tmp_path / "synthetic-wayground.xlsx"
    path.write_bytes(workbook())
    result = subprocess.run(
        [shutil.which("node"), "frontend/scripts/live-wayground-smoke.mjs"],
        cwd=Path(__file__).resolve().parents[2],
        capture_output=True,
        text=True,
        timeout=120,
        env={
            **os.environ,
            "TTH_BACKEND_URL": live_server.url.replace("localhost", "127.0.0.1"),
            "TTH_WAYGROUND_ROUND": str(way[0].pk),
            "TTH_WAYGROUND_FILE": str(path),
        },
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert WaygroundReport.objects.count() == 1 and ScoreRevision.objects.count() == 2
