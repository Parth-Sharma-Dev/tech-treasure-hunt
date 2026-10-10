"""Private signed exports, inventories and two-person reconciliation after restore."""

import json
from datetime import datetime
from uuid import UUID, uuid4

from django.core import serializers
from django.core.management.color import no_style
from django.core.serializers.json import DjangoJSONEncoder
from django.core.signing import BadSignature, Signer
from django.db import connection, transaction
from django.db.models import F

from . import models as m
from .api import ApiProblem
from .clock import database_now
from .corrections import evidence_refs
from .results import (
    audit_replay,
    digest,
    record_action,
    require_result_role,
    require_result_view,
    validate_request,
)
from .rules import require_staff_permission

EXPORT_SIGNER = Signer(salt="competition.evidence-export.v1")


def locked_evidence_round(round_id):
    """Use the roster lock order for shared cohort evidence and access revocation."""
    cohort = m.Round.objects.filter(pk=round_id).values_list("is_demo", flat=True).first()
    if cohort is None:
        raise ApiProblem("not_found", "Round not found.", 404)
    if m.Round.objects.filter(pk=round_id, number=5).exists():
        from .buzzer import admission_fence

        # Drain native admissions before taking roster/team locks, like window closure.
        admission_fence(round_id)
    from .roster import locked_roster

    rounds, _ = locked_roster(cohort)
    # Faculty publication locks the same rows before changing approved profiles.
    list(m.FacultyProfile.objects.select_for_update().filter(is_demo=cohort).order_by("pk"))
    return next(item for item in rounds if item.pk == round_id)


def require_stopped_cohort(round):
    if m.Round.objects.filter(is_demo=round.is_demo, state__in=["LIVE", "FROZEN"]).exists():
        raise ApiProblem(
            "invalid_transition",
            "Stop all cohort play before recovery revokes shared team access.",
            409,
        )


class EvidenceEncoder(DjangoJSONEncoder):
    def default(self, value):
        if isinstance(value, datetime):
            return value.isoformat()
        return super().default(value)


def contains(value, name, ids):
    if isinstance(value, dict):
        return value.get(name) in ids or any(contains(item, name, ids) for item in value.values())
    if isinstance(value, list):
        return any(contains(item, name, ids) for item in value)
    return False


def round_queries(round, extended=True):
    mission_ids = set(m.Mission.objects.filter(round=round).values_list("pk", flat=True))
    incident_ids = set(m.Incident.objects.filter(round=round).values_list("pk", flat=True))
    faculty_ids = set(
        m.FacultyProfile.objects.filter(is_demo=round.is_demo).values_list("pk", flat=True)
    )
    roster_ids = set(
        m.RosterProposal.objects.filter(payload__is_demo=round.is_demo).values_list("pk", flat=True)
    )
    team_ids = set(m.Team.objects.filter(is_demo=round.is_demo).values_list("pk", flat=True))
    audits = [
        item.pk
        for item in m.AuditEvent.objects.all()
        if contains(item.before, "round_id", {round.pk})
        or contains(item.after, "round_id", {round.pk})
        or contains(item.before, "mission_id", mission_ids)
        or contains(item.after, "mission_id", mission_ids)
        or item.incident_id in incident_ids
        or extended
        and (
            item.action == "publish_faculty"
            and contains(item.after, "faculty_id", faculty_ids)
            or item.action in ["propose_roster", "review_roster"]
            and contains(item.after, "proposal_id", roster_ids)
            or item.action == "team_credentials"
            and contains(item.after, "team_id", team_ids)
        )
    ]
    queries = [m.Round.objects.filter(pk=round.pk), m.Mission.objects.filter(round=round)]
    for model in [
        m.Incident,
        m.RoundPhase,
        m.SubmissionDecision,
        m.ResolutionProposal,
        m.ResultProposal,
        m.ResultSnapshot,
        m.PaperWindow,
        m.PaperProposal,
        m.PaperSlip,
    ]:
        queries.append(model.objects.filter(round=round))
    for model in [m.Visit, m.AttemptState, m.MissionResolution, m.Completion]:
        queries.append(model.objects.filter(mission__round=round))
    if extended:
        if round.number == 5:
            queries.extend(
                [
                    m.BuzzerQuestion.objects.filter(round=round),
                    m.BuzzerWindow.objects.filter(round=round),
                    m.BuzzerClosure.objects.filter(window__round=round),
                    m.BuzzerPress.objects.filter(window__round=round),
                    m.BuzzerAnswerEvidence.objects.filter(window__round=round),
                    m.BuzzerScoreRevision.objects.filter(window__round=round),
                ]
            )
        for model in [
            m.CodingTask,
            m.CodingWorkstation,
            m.CodingRevision,
            m.CodingSubmission,
            m.ImportBatch,
            m.ScoreRevision,
            m.GreenCardRevision,
            m.WaygroundReport,
            m.ExternalVoidProposal,
        ]:
            queries.append(model.objects.filter(round=round))
        for model in [m.CodingJudgmentProposal, m.CodingJudgment]:
            queries.append(model.objects.filter(submission__round=round))
        queries.extend(
            [
                m.ExternalQuestionVoid.objects.filter(proposal__round=round),
                m.FacultyProfile.objects.filter(pk__in=faculty_ids),
                m.RosterProposal.objects.filter(pk__in=roster_ids),
            ]
        )
    queries.append(m.AuditEvent.objects.filter(pk__in=audits))
    return {query.model._meta.model_name: query.order_by("pk") for query in queries}


def export_objects(round, extended=True):
    return json.loads(
        serializers.serialize(
            "json",
            [item for query in round_queries(round, extended).values() for item in query],
            cls=EvidenceEncoder,
        )
    )


def inventory(objects):
    return {f"{item['model']}:{item['pk']}": digest(item) for item in objects}


def carry_provenance(round):
    """Bind earlier final attempts without replaying their clocks or publications."""
    from .buzzer_scores import carry_over
    from .results import latest_snapshot

    _, _, basis, errors = carry_over(round)
    dependencies = []
    attempts = []
    for number in range(1, 5):
        prior = (
            m.Round.objects.filter(number=number, is_demo=round.is_demo)
            .order_by("-attempt_no")
            .first()
        )
        if prior:
            # Earlier recovery advances controls and adds recovery incidents. Bind
            # approved identity/state, not those operational bookkeeping changes.
            attempts.append(
                {
                    "round_id": prior.pk,
                    "attempt_id": str(prior.attempt_id),
                    "attempt_no": prior.attempt_no,
                    "state": prior.state,
                    "rules_digest": prior.rules_digest,
                    "approval_digest": prior.approval_digest,
                    "rules_snapshot_digest": digest(prior.rules_snapshot),
                }
            )
            snapshot = latest_snapshot(prior)
            if snapshot:
                dependencies.append(snapshot)
            dependencies.extend(
                m.Incident.objects.filter(round=prior, material=True)
                .exclude(category="RECOVERY")
                .order_by("pk")
            )
    return json.loads(
        json.dumps(
            {
                "basis": basis,
                "attempts": attempts,
                "errors": errors,
                "inventory": inventory(
                    json.loads(serializers.serialize("json", dependencies, cls=EvidenceEncoder))
                ),
            },
            cls=DjangoJSONEncoder,
        )
    )


def make_bundle(round):
    if round.state not in ["ENDED", "PROVISIONAL", "FINALIZED"]:
        raise ApiProblem(
            "invalid_transition",
            "Capture a reconciliation bundle after ending and persisting the round.",
            409,
        )
    objects = export_objects(round)
    teams = list(
        m.Team.objects.filter(is_demo=round.is_demo)
        .order_by("pk")
        .values(
            "id",
            "code",
            "name",
            "leader_name",
            "member_count",
            "roster_reference",
            "roster_digest",
            "status",
            "session_version",
            "user_id",
        )
    )
    sessions = list(
        m.TeamSession.objects.filter(team__is_demo=round.is_demo)
        .order_by("pk")
        .values(
            "id",
            "team_id",
            "session_version",
            "created_at",
            "last_seen_at",
            "expires_at",
            "revoked_at",
        )
    )
    payload = json.loads(
        json.dumps(
            {
                "format": "round-evidence-v3" if round.number == 5 else "round-evidence-v2",
                "attempt_id": str(round.attempt_id),
                "round_id": round.pk,
                "rules_digest": round.rules_digest,
                "captured_at": database_now(),
                "objects": objects,
                "inventory": inventory(objects),
                "teams": teams,
                "sessions": sessions,
                **({"carry_over_provenance": carry_provenance(round)} if round.number == 5 else {}),
            },
            cls=DjangoJSONEncoder,
        )
    )
    return {
        "signed_bundle": EXPORT_SIGNER.sign_object(payload, compress=True),
        "manifest": {key: value for key, value in payload.items() if key != "objects"},
    }


def read_bundle(value, round):
    try:
        payload = EXPORT_SIGNER.unsign_object(value)
    except (BadSignature, ValueError, TypeError):
        raise ApiProblem(
            "invalid_evidence", "The export signature is invalid or its signing key changed."
        ) from None
    if (
        not isinstance(payload, dict)
        or payload.get("format")
        not in ["round-evidence-v1", "round-evidence-v2", "round-evidence-v3"]
        or round.number == 5
        and (
            payload.get("format") != "round-evidence-v3"
            or not isinstance(payload.get("carry_over_provenance"), dict)
        )
        or payload.get("format") == "round-evidence-v3"
        and round.number != 5
        or payload.get("format") == "round-evidence-v1"
        and round.number != 1
        or payload.get("round_id") != round.pk
        or payload.get("attempt_id") != str(round.attempt_id)
        or payload.get("rules_digest") != round.rules_digest
        or payload.get("inventory") != inventory(payload.get("objects", []))
    ):
        raise ApiProblem(
            "invalid_evidence",
            "The export belongs to different rules/attempt or has a damaged inventory.",
        )
    return payload


def compare_bundle(round, payload):
    current = inventory(export_objects(round, payload["format"] != "round-evidence-v1"))
    baseline = payload["inventory"]
    comparison = {
        "missing": [key for key in baseline if key not in current],
        "changed": [key for key in baseline if key in current and baseline[key] != current[key]],
        "additional": [key for key in current if key not in baseline],
    }
    if payload["format"] != "round-evidence-v1":
        comparison["team_changes"] = team_changes(round, payload)
    if round.number == 5:
        comparison["carry_over_changed"] = payload["carry_over_provenance"] != carry_provenance(
            round
        )
    return comparison


def team_changes(round, payload):
    """Roster/account identities require manual recovery; access is never replayed."""
    current = {team.pk: team for team in m.Team.objects.filter(is_demo=round.is_demo)}
    changes = []
    for item in payload["teams"]:
        team = current.get(item["id"])
        if team is None:
            changes.append({"team_id": item["id"], "kind": "missing_identity"})
        elif any(
            getattr(team, field) != item[field]
            for field in [
                "code",
                "name",
                "leader_name",
                "member_count",
                "roster_reference",
                "user_id",
            ]
        ):
            changes.append({"team_id": item["id"], "kind": "changed_identity"})
        elif team.status != item["status"]:
            changes.append(
                {
                    "team_id": item["id"],
                    "kind": "status",
                    "current": team.status,
                    "checkpoint": item["status"],
                }
            )
    changes.extend(
        {"team_id": pk, "kind": "additional_identity"}
        for pk in current
        if pk not in {item["id"] for item in payload["teams"]}
    )
    return changes


def checkpoint_digest(round):
    objects = [
        item
        for item in export_objects(round)
        if not (
            item["model"] == "competition.auditevent"
            and item["fields"]["action"] in ["propose_recovery", "approve_recovery"]
        )
    ]
    return digest(
        {
            "inventory": inventory(objects),
            **({"carry_over_provenance": carry_provenance(round)} if round.number == 5 else {}),
        }
    )


@transaction.atomic
def propose_recovery(round_id, actor, data):
    require_result_role(actor)
    action_id, reason = validate_request(data)
    round = locked_evidence_round(round_id)
    if round.number not in [1, 2, 3, 4, 5] or round.state in ["LIVE", "FROZEN"]:
        raise ApiProblem(
            "invalid_transition",
            "Stop in-scope round play before reconciling a restored database.",
            409,
        )
    bundle = data.get("signed_bundle")
    if not isinstance(bundle, str) or len(bundle) > 8_000_000:
        raise ApiProblem("invalid_request", "Supply a bounded signed evidence bundle.")
    payload = read_bundle(bundle, round)
    refs = evidence_refs(data)
    fingerprint = {**data, "kind": "recovery_propose", "round_id": round_id, "actor_id": actor.pk}
    if original := audit_replay(action_id, fingerprint):
        return original
    require_stopped_cohort(round)
    if (
        type(data.get("expected_version")) is not int
        or data["expected_version"] != round.control_version
    ):
        raise ApiProblem(
            "stale_evidence", "Refresh the restored round before proposing recovery.", 409
        )
    comparison = compare_bundle(round, payload)
    # Freeze access immediately. A restored revoked session must not survive until review.
    now = database_now()
    m.TeamSession.objects.filter(team__is_demo=round.is_demo, revoked_at__isnull=True).update(
        revoked_at=now
    )
    m.Team.objects.filter(is_demo=round.is_demo).update(session_version=F("session_version") + 1)
    incident = m.Incident.objects.create(
        round=round,
        owner=actor,
        category="RECOVERY",
        material=True,
        opened_at=now,
        affected_scope={"summary": reason, "comparison": comparison},
        evidence_references=refs,
    )
    proposal = m.RecoveryProposal.objects.create(
        round=round,
        maker=actor,
        reason=reason,
        incident=incident,
        expected_version=round.control_version,
        evidence_digest=checkpoint_digest(round),
        payload={"signed_bundle": bundle, "comparison": comparison, "evidence_refs": refs},
    )
    response = {"recovery_proposal_id": proposal.pk, "incident_id": incident.pk, **comparison}
    record_action(action_id, actor, "propose_recovery", reason, fingerprint, response)
    return response


def restore_missing(round, payload):
    """Append absent signed records; never overwrite conflicting current evidence."""
    extended = payload["format"] != "round-evidence-v1"
    if round.number == 5 and (
        payload["carry_over_provenance"] != carry_provenance(round)
        or payload["carry_over_provenance"].get("errors")
    ):
        raise ApiProblem(
            "evidence_gap",
            "Carry-over dependencies differ or are incomplete. Recover earlier rounds first.",
            409,
        )
    queries = round_queries(round, extended)
    allowed = {query.model._meta.label_lower: query.model for query in queries.values()}
    pending = []
    mutable = {
        "competition.round",
        "competition.visit",
        "competition.attemptstate",
        "competition.completion",
        "competition.incident",
    }
    baseline = payload["inventory"]
    if extended:
        changes = team_changes(round, payload)
        if any(item["kind"] != "status" for item in changes):
            raise ApiProblem(
                "evidence_conflict",
                "Roster/account identities differ; reconcile them before recovery.",
                409,
            )
        # Replay only stricter restrictions, never ACTIVE over a revoked/withdrawn identity.
        priority = {"ACTIVE": 0, "WITHDRAWN": 1, "DISQUALIFIED": 2}
        for item in payload["teams"]:
            team = m.Team.objects.get(pk=item["id"], is_demo=round.is_demo)
            if priority[item["status"]] > priority[team.status]:
                team.status = item["status"]
                team.save(update_fields=["status"])
    for query in queries.values():
        for obj in query:
            key = f"{obj._meta.label_lower}:{obj.pk}"
            if key not in baseline and not (
                isinstance(obj, m.Incident)
                and obj.category == "RECOVERY"
                or isinstance(obj, m.AuditEvent)
                and obj.action in ["propose_recovery", "approve_recovery"]
            ):
                raise ApiProblem(
                    "evidence_conflict",
                    "Additional evidence exists beyond this checkpoint. Use a newer full export.",
                    409,
                )
    for item in payload["objects"]:
        model = allowed.get(item["model"])
        if model is None:
            raise ApiProblem(
                "invalid_evidence", "The export contains an unsupported evidence model."
            )
        existing = model.objects.filter(pk=item["pk"]).first()
        if existing:
            current = json.loads(serializers.serialize("json", [existing], cls=EvidenceEncoder))[0]
            if current != item:
                if item["model"] not in mutable:
                    raise ApiProblem(
                        "evidence_conflict",
                        "Immutable evidence differs; preserve both databases for investigation.",
                        409,
                    )
                if item["model"] == "competition.round":
                    if any(
                        current["fields"][field] != item["fields"][field]
                        for field in [
                            "attempt_id",
                            "rules_digest",
                            "rules_snapshot",
                            "approval_digest",
                        ]
                    ):
                        raise ApiProblem(
                            "evidence_conflict", "The restored approved configuration differs.", 409
                        )
                pending.append(item)
        else:
            pending.append(item)
    # Dependencies may refer forward within the signed bundle; PostgreSQL checks at commit.
    if extended:
        sessions = {item["id"]: item for item in payload["sessions"]}
        for item in pending:
            if item["model"] not in ["competition.codingworkstation", "competition.buzzerpress"]:
                continue
            session_id = item["fields"]["session"]
            session = m.TeamSession.objects.filter(pk=session_id).first()
            if session is not None:
                if session.team_id != item["fields"]["team"]:
                    raise ApiProblem(
                        "evidence_conflict", "Historical session identity differs.", 409
                    )
                continue
            retained = sessions.get(session_id)
            if not retained or retained["team_id"] != item["fields"]["team"]:
                raise ApiProblem(
                    "evidence_gap", "Missing retained historical session identity.", 409
                )
            # A tombstone keeps historical FKs without restoring a cookie or usable session.
            m.TeamSession.objects.create(
                **{key: value for key, value in retained.items() if key != "revoked_at"},
                session_key=uuid4().hex,
                revoked_at=database_now(),
            )
        pending_keys = {(item["model"], str(item["pk"])) for item in pending}
        for item in pending:
            model = allowed[item["model"]]
            for field in model._meta.fields:
                if not field.many_to_one and not field.one_to_one:
                    continue
                identity = item["fields"].get(field.name)
                target = field.remote_field.model
                if (
                    identity is not None
                    and (target._meta.label_lower, str(identity)) not in pending_keys
                    and not target.objects.filter(pk=identity).exists()
                ):
                    raise ApiProblem(
                        "evidence_gap",
                        "A retained record needs missing account or earlier-round evidence.",
                        409,
                    )
    for obj in serializers.deserialize("json", json.dumps(pending), ignorenonexistent=False):
        obj.save()
    with connection.cursor() as cursor:
        for statement in connection.ops.sequence_reset_sql(
            no_style(), [*allowed.values(), m.TeamSession]
        ):
            cursor.execute(statement)
    round.refresh_from_db()
    if round.state in ["LIVE", "FROZEN"]:
        raise ApiProblem(
            "incomplete_checkpoint",
            "Use an ended checkpoint; live clock recovery needs supervised reconciliation.",
            409,
        )


@transaction.atomic
def approve_recovery(round_id, actor, data):
    require_staff_permission(actor, "verify_evidence")
    action_id, reason = validate_request(data)
    round = locked_evidence_round(round_id)
    fingerprint = {**data, "kind": "recovery_approve", "round_id": round_id, "actor_id": actor.pk}
    if original := audit_replay(action_id, fingerprint):
        return original
    require_stopped_cohort(round)
    proposal = (
        m.RecoveryProposal.objects.select_related("incident", "maker")
        .filter(pk=data.get("proposal_id"), round=round)
        .first()
        if type(data.get("proposal_id")) is int
        else None
    )
    if proposal is None:
        raise ApiProblem("not_found", "Recovery proposal not found.", 404)
    if proposal.maker_id == actor.pk:
        raise ApiProblem(
            "independent_reviewer", "A different verifier must reconcile recovery evidence.", 403
        )
    require_result_role(proposal.maker)
    if data.get("evidence_confirmed") is not True:
        raise ApiProblem(
            "evidence_required", "Confirm independent review of missing intervals and coverage."
        )
    if proposal.incident.closed_at is not None:
        raise ApiProblem("already_applied", "This recovery proposal was already reviewed.", 409)
    if (
        proposal.expected_version != round.control_version
        or proposal.evidence_digest != checkpoint_digest(round)
    ):
        raise ApiProblem("stale_evidence", "Round changed during recovery review.", 409)
    if data.get("reject") is not True:
        payload = read_bundle(proposal.payload["signed_bundle"], round)
        if round.state == "FINALIZED" or any(
            item["model"] == "competition.resultsnapshot" and item["fields"]["status"] == "FINAL"
            for item in payload["objects"]
        ):
            require_staff_permission(actor, "publish_results")
        restore_missing(round, payload)
        # Also revoke sessions issued between proposal and independent review.
        m.TeamSession.objects.filter(team__is_demo=round.is_demo, revoked_at__isnull=True).update(
            revoked_at=database_now()
        )
        m.Team.objects.filter(is_demo=round.is_demo).update(
            session_version=F("session_version") + 1
        )
        from .results import build_preview

        preview = build_preview(round, database_now())
        gaps = preview["evidence_gaps"] + (
            preview.get("configuration_errors", []) if round.number == 5 else []
        )
        if gaps:
            raise ApiProblem("evidence_gap", " ".join(gaps), 409)
        if round.number == 5:
            verify_recovered_award(round, preview)
        round.control_version = max(round.control_version, proposal.expected_version) + 1
        round.save(update_fields=["control_version"])
    else:
        # Rejection preserves the material coverage gap; close only with an explicit disposition.
        raise ApiProblem(
            "coverage_gap", "Retain the recovery incident until missing coverage is resolved.", 409
        )
    proposal.incident.closed_at = database_now()
    proposal.incident.decision = reason
    proposal.incident.save(update_fields=["closed_at", "decision"])
    response = {"recovery_proposal_id": proposal.pk, "reconciled": True}
    record_action(action_id, actor, "approve_recovery", reason, fingerprint, response)
    return response


def verify_recovered_award(round, preview):
    """Reproduce published credit and original completion times, never invent an award."""
    from .results import latest_snapshot

    snapshot = latest_snapshot(round)
    if not snapshot:
        return
    current = {entry["team_code"]: entry for entry in preview["entries"]}
    fields = [
        "score",
        "max_score",
        "stage_scores",
        "round5_score",
        "carry_over_score",
        "carry_over_scores",
        "last_correct_at",
    ]
    if len(snapshot.ranked_entries) != len(current) or any(
        entry.get("team_code") not in current
        or any(entry.get(field) != current[entry["team_code"]].get(field) for field in fields)
        for entry in snapshot.ranked_entries
    ):
        raise ApiProblem(
            "evidence_conflict", "Published standings do not reproduce retained credit.", 409
        )
    if snapshot.status == "FINAL":
        winners = snapshot.metadata.get("winner_codes", [])
        top = [entry["team_code"] for entry in snapshot.ranked_entries if entry.get("rank") == 1]
        if (
            snapshot.qualifier_codes
            or len(winners) != 1
            or winners[0] not in top
            or snapshot.maker_id == snapshot.approver_id
        ):
            raise ApiProblem("evidence_conflict", "The retained event award is inconsistent.", 409)


@transaction.atomic
def evidence_page(round_id, actor, kind, cursor=None, limit=200):
    require_result_view(actor)
    round = locked_evidence_round(round_id)
    queries = round_queries(round)
    if kind not in queries:
        raise ApiProblem("invalid_request", "Choose a supported evidence export type.")
    if type(limit) is not int or not 1 <= limit <= 500:
        raise ApiProblem("invalid_request", "Export limits must be from 1 to 500.")
    if kind == "waygroundreport":
        limit = min(limit, 2)  # Original workbook bytes need a smaller bounded page.
    stamp = checkpoint_digest(round)
    offset = 0
    if cursor:
        try:
            page = EXPORT_SIGNER.unsign_object(cursor)
        except (BadSignature, ValueError, TypeError):
            raise ApiProblem("invalid_cursor", "Export cursor is invalid.") from None
        if (
            page.get("round_id") != round_id
            or page.get("kind") != kind
            or page.get("stamp") != stamp
        ):
            raise ApiProblem(
                "stale_evidence", "Evidence changed during export. Restart the export.", 409
            )
        offset = page["offset"]
    query = queries[kind]
    items = json.loads(
        serializers.serialize("json", query[offset : offset + limit], cls=EvidenceEncoder)
    )
    next_cursor = (
        EXPORT_SIGNER.sign_object(
            {"round_id": round_id, "kind": kind, "stamp": stamp, "offset": offset + limit}
        )
        if query.count() > offset + limit
        else None
    )
    manifest = {
        "round_id": round_id,
        "kind": kind,
        "stamp": stamp,
        "inventory": inventory(items),
        "next_cursor": next_cursor,
    }
    return {
        "objects": items,
        "manifest": manifest,
        "signature": EXPORT_SIGNER.sign_object(manifest),
        "next_cursor": next_cursor,
    }


def verify_receipts(round_id, actor, tokens):
    require_result_view(actor)
    round = m.Round.objects.filter(pk=round_id).first()
    if round is None:
        raise ApiProblem("not_found", "Round not found.", 404)
    if (
        not isinstance(tokens, list)
        or not 1 <= len(tokens) <= 100
        or any(not isinstance(token, str) or len(token) > 32000 for token in tokens)
    ):
        raise ApiProblem("invalid_request", "Supply from one to 100 signed receipts.")
    results = []
    signer = Signer(salt="competition.accepted-receipt.v1")
    for token in tokens:
        try:
            payload = signer.unsign_object(token)
            if (
                not isinstance(payload, dict)
                or payload.get("outcome") != "accepted"
                or payload.get("round_id") != round.pk
                or payload.get("attempt_id") != str(round.attempt_id)
            ):
                raise ValueError("Wrong attempt")
            decision = m.SubmissionDecision.objects.filter(
                pk=UUID(payload.get("decision_id")), round=round
            ).first()
            state = (
                "missing_decision"
                if decision is None
                else "verified"
                if decision.response_snapshot.get("receipt") == token
                else "conflict"
            )
            results.append(
                {
                    "decision_id": payload["decision_id"],
                    "team_code": payload.get("team_code"),
                    "status": state,
                }
            )
        except (BadSignature, ValueError, TypeError, KeyError):
            results.append({"status": "invalid"})
    return {
        "receipts": results,
        "coverage_complete": all(item["status"] == "verified" for item in results),
    }


def spreadsheet_cell(value):
    text = value if isinstance(value, str) else json.dumps(value, cls=EvidenceEncoder)
    return (
        "'" + text
        if text.lstrip().startswith(("=", "+", "-", "@", "\t", "\r", "\n"))
        or text.startswith(("\t", "\r", "\n"))
        else text
    )
