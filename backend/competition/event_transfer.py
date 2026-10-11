"""Private transfer of unused real event drafts, without accounts or event history."""

import base64
import hashlib
import json
import zipfile
from pathlib import Path

from django.core.management.base import CommandError
from django.db import transaction
from django.db.models import Max

from .models import (
    AuditEvent,
    BuzzerQuestion,
    CodingTask,
    EventContentSource,
    FacultyProfile,
    HuntCode,
    Mission,
    Round,
    RoundInformation,
)

ROUND_FIELDS = (
    "number",
    "title",
    "delivery_mode",
    "rules_version",
    "rules",
    "advancement_count",
    "active_budget_ms",
)
MISSION_FIELDS = (
    "public_id",
    "token",
    "fallback_code",
    "hint",
    "symbol",
    "clue_type",
    "qr_location",
    "clue_location",
    "difficulty",
    "points",
    "keyword",
    "is_practice",
)
FACULTY_FIELDS = (
    "display_name",
    "role",
    "location",
    "contact_channel",
    "photo_url",
    "consent_reference",
)
LIMIT = 16 * 1024 * 1024


def fields(obj, names):
    return {name: getattr(obj, name) for name in names}


def source_key(source):
    return f"{source.round.number}:{source.kind}:{source.sha256}"


def export_package(path):
    with transaction.atomic():
        rounds = list(Round.objects.select_for_update().filter(is_demo=False).order_by("number"))
        if len(rounds) != 5 or [r.number for r in rounds] != [1, 2, 3, 4, 5]:
            raise CommandError(
                "Export requires exactly one real draft for each of the five rounds."
            )
        if any(r.state != "DRAFT" or r.approved_at for r in rounds):
            raise CommandError("Only unused, unapproved DRAFT rounds can be exported.")
        if any(r.rules.get("faculty_panels") for r in rounds):
            raise CommandError("Configure faculty panel assignments on the destination instead.")
        if (
            CodingTask.objects.filter(round__in=rounds).exists()
            or BuzzerQuestion.objects.filter(round__in=rounds).exists()
            or RoundInformation.objects.filter(round__in=rounds).exists()
        ):
            raise CommandError(
                "This transfer covers initial round/mission/source/faculty drafts only."
            )
        missions = list(Mission.objects.filter(round__in=rounds).select_related("round"))
        if any(m.clue_image or m.answer_verifiers for m in missions):
            raise CommandError(
                "Uploaded images and mission-bound answer hashes need separate migration."
            )
        sources = list(EventContentSource.objects.filter(round__in=rounds).select_related("round"))
        faculty = list(FacultyProfile.objects.filter(is_demo=False))
        if any(f.published_at or f.published_snapshot for f in faculty):
            raise CommandError("Only unpublished faculty drafts can be transferred.")
        payload = {
            "version": "event-drafts-v1",
            "rounds": [fields(r, ROUND_FIELDS) for r in rounds],
            "missions": [{"round": m.round.number, **fields(m, MISSION_FIELDS)} for m in missions],
            "sources": [
                {
                    "key": source_key(s),
                    "round": s.round.number,
                    "kind": s.kind,
                    "filename": s.filename,
                    "sha256": s.sha256,
                    "content": s.content,
                    "original_base64": base64.b64encode(bytes(s.original_bytes)).decode(),
                }
                for s in sources
            ],
            "codes": [
                {
                    "round": c.round.number,
                    "source": source_key(c.source),
                    "code": c.code,
                    "keyword": c.keyword,
                }
                for c in HuntCode.objects.filter(round__in=rounds).select_related(
                    "round", "source__round"
                )
            ],
            "faculty": [fields(f, FACULTY_FIELDS) for f in faculty],
        }
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True).encode()
    if len(raw) > LIMIT:
        raise CommandError("Package exceeds the 16 MB private-content limit.")
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "x", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("event.json", raw)
    return payload


def read_package(path):
    if Path(path).stat().st_size > LIMIT:
        raise CommandError("Package exceeds the 16 MB limit.")
    with zipfile.ZipFile(path) as archive:
        if archive.namelist() != ["event.json"] or archive.getinfo("event.json").file_size > LIMIT:
            raise CommandError("Expected one bounded event.json entry; no files are extracted.")
        payload = json.loads(archive.read("event.json"))
    if (
        not isinstance(payload, dict)
        or set(payload) != {"version", "rounds", "missions", "sources", "codes", "faculty"}
        or payload["version"] != "event-drafts-v1"
    ):
        raise CommandError("Unrecognized private draft package.")
    for name in ("rounds", "missions", "sources", "codes", "faculty"):
        if not isinstance(payload[name], list):
            raise CommandError("Package inventories must be lists.")
    if len(payload["rounds"]) != 5 or sorted(r["number"] for r in payload["rounds"]) != [
        1,
        2,
        3,
        4,
        5,
    ]:
        raise CommandError("Expected exactly five distinct round numbers.")
    return payload


def require_fields(row, expected):
    if not isinstance(row, dict) or set(row) != set(expected):
        raise CommandError("Unexpected fields in private content inventory.")


@transaction.atomic
def import_package(path, actor, dry_run=False):
    payload = read_package(path)
    # Serialize with ordinary round/roster workflows. Existing live event data is never replaced.
    existing = list(Round.objects.select_for_update().filter(is_demo=False).order_by("number"))
    if any(
        r.state != "DRAFT" or r.approved_at or r.rules_version or r.rules or r.owners
        for r in existing
    ):
        raise CommandError("Destination real rounds must be absent or empty, unapproved drafts.")
    if len({r.number for r in existing}) != len(existing):
        raise CommandError("Destination has multiple real attempts; review instead of merging.")
    if (
        Mission.objects.filter(round__is_demo=False).exists()
        or EventContentSource.objects.filter(round__is_demo=False).exists()
        or HuntCode.objects.filter(round__is_demo=False).exists()
        or FacultyProfile.objects.filter(is_demo=False).exists()
        or CodingTask.objects.filter(round__is_demo=False).exists()
        or BuzzerQuestion.objects.filter(round__is_demo=False).exists()
        or RoundInformation.objects.filter(round__is_demo=False).exists()
    ):
        raise CommandError("Destination already contains real content; refusing to overwrite it.")
    rounds = {r.number: r for r in existing}
    for row in payload["rounds"]:
        require_fields(row, ROUND_FIELDS)
        if not isinstance(row["rules"], dict) or row["rules"].get("faculty_panels"):
            raise CommandError("Round policies must exclude database-specific faculty assignments.")
        number = row["number"]
        if number not in rounds:
            attempt = Round.objects.filter(number=number).aggregate(n=Max("attempt_no"))["n"] or 0
            rounds[number] = Round(number=number, attempt_no=attempt + 1)
        elif rounds[number].title != row["title"]:
            raise CommandError("An existing draft has a different title; review it first.")
        target = rounds[number]
        for key, value in row.items():
            setattr(target, key, value)
        target.full_clean()
        target.save()
    sources = {}
    for row in payload["sources"]:
        require_fields(
            row, ("key", "round", "kind", "filename", "sha256", "content", "original_base64")
        )
        raw = base64.b64decode(row["original_base64"], validate=True)
        if hashlib.sha256(raw).hexdigest() != row["sha256"]:
            raise CommandError("Original source checksum differs; nothing will be imported.")
        if row["key"] != f"{row['round']}:{row['kind']}:{row['sha256']}" or row["key"] in sources:
            raise CommandError("Original source identity is inconsistent or duplicated.")
        source = EventContentSource(
            round=rounds[row["round"]],
            kind=row["kind"],
            filename=row["filename"],
            sha256=row["sha256"],
            original_bytes=raw,
            content=row["content"],
            prepared_by=actor,
        )
        source.full_clean()
        source.save()
        sources[row["key"]] = source
    for row in payload["missions"]:
        require_fields(row, ("round", *MISSION_FIELDS))
        Mission.objects.create(
            round=rounds[row["round"]],
            prepared_by=actor,
            available=False,
            **{key: row[key] for key in MISSION_FIELDS},
        )
    for row in payload["codes"]:
        require_fields(row, ("round", "source", "code", "keyword"))
        source = sources[row["source"]]
        if source.round_id != rounds[row["round"]].pk or source.kind != "CODE_POOL":
            raise CommandError("A code must reference its own round's original code pool.")
        code = HuntCode(round=source.round, source=source, code=row["code"], keyword=row["keyword"])
        code.full_clean()
        code.save()
    for row in payload["faculty"]:
        require_fields(row, FACULTY_FIELDS)
        faculty = FacultyProfile(**row, prepared_by=actor, visible=False)
        faculty.full_clean(exclude=["consent_reference"])
        faculty.save()
    AuditEvent.objects.create(
        actor=actor,
        action="import_event_drafts",
        after={
            "round_ids": {str(n): r.pk for n, r in rounds.items()},
            "missions": len(payload["missions"]),
            "codes": len(payload["codes"]),
        },
        reason="Private initial event drafts transferred without accounts, approval or results.",
    )
    summary = {
        "round_ids": {n: r.pk for n, r in rounds.items()},
        "missions": len(payload["missions"]),
        "codes": len(payload["codes"]),
        "faculty": len(payload["faculty"]),
    }
    if dry_run:
        transaction.set_rollback(True)
    return summary
