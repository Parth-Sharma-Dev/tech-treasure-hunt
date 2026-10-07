"""Private signed exports, inventories and two-person reconciliation after restore."""

import json
from datetime import datetime
from uuid import UUID

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
    locked_round,
    record_action,
    require_result_role,
    require_result_view,
    validate_request,
)
from .rules import require_staff_permission

EXPORT_SIGNER = Signer(salt="competition.evidence-export.v1")


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


def round_queries(round):
    mission_ids = set(m.Mission.objects.filter(round=round).values_list("pk", flat=True))
    incident_ids = set(m.Incident.objects.filter(round=round).values_list("pk", flat=True))
    audits = [
        item.pk
        for item in m.AuditEvent.objects.all()
        if contains(item.before, "round_id", {round.pk})
        or contains(item.after, "round_id", {round.pk})
        or contains(item.before, "mission_id", mission_ids)
        or contains(item.after, "mission_id", mission_ids)
        or item.incident_id in incident_ids
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
    queries.append(m.AuditEvent.objects.filter(pk__in=audits))
    return {query.model._meta.model_name: query.order_by("pk") for query in queries}


def export_objects(round):
    return json.loads(
        serializers.serialize(
            "json",
            [item for query in round_queries(round).values() for item in query],
            cls=EvidenceEncoder,
        )
    )


def inventory(objects):
    return {f"{item['model']}:{item['pk']}": digest(item) for item in objects}


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
        .values("id", "code", "status", "session_version")
    )
    sessions = list(
        m.TeamSession.objects.filter(team__is_demo=round.is_demo)
        .order_by("pk")
        .values("id", "team_id", "revoked_at")
    )
    payload = json.loads(
        json.dumps(
            {
                "format": "round-evidence-v1",
                "attempt_id": str(round.attempt_id),
                "round_id": round.pk,
                "rules_digest": round.rules_digest,
                "captured_at": database_now(),
                "objects": objects,
                "inventory": inventory(objects),
                "teams": teams,
                "sessions": sessions,
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
        or payload.get("format") != "round-evidence-v1"
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
    current = inventory(export_objects(round))
    baseline = payload["inventory"]
    return {
        "missing": [key for key in baseline if key not in current],
        "changed": [key for key in baseline if key in current and baseline[key] != current[key]],
        "additional": [key for key in current if key not in baseline],
    }


def checkpoint_digest(round):
    objects = [
        item
        for item in export_objects(round)
        if not (
            item["model"] == "competition.auditevent"
            and item["fields"]["action"] in ["propose_recovery", "approve_recovery"]
        )
    ]
    return digest(inventory(objects))


@transaction.atomic
def propose_recovery(round_id, actor, data):
    require_result_role(actor)
    action_id, reason = validate_request(data)
    round = locked_round(round_id)
    if round.number != 1 or round.state in ["LIVE", "FROZEN"]:
        raise ApiProblem(
            "invalid_transition", "Stop Round 1 play before reconciling a restored database.", 409
        )
    bundle = data.get("signed_bundle")
    if not isinstance(bundle, str) or len(bundle) > 8_000_000:
        raise ApiProblem("invalid_request", "Supply a bounded signed evidence bundle.")
    payload = read_bundle(bundle, round)
    refs = evidence_refs(data)
    fingerprint = {**data, "kind": "recovery_propose", "round_id": round_id, "actor_id": actor.pk}
    if original := audit_replay(action_id, fingerprint):
        return original
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
    queries = round_queries(round)
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
    for obj in serializers.deserialize("json", json.dumps(pending), ignorenonexistent=False):
        obj.save()
    with connection.cursor() as cursor:
        for statement in connection.ops.sequence_reset_sql(no_style(), list(allowed.values())):
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
    round = locked_round(round_id)
    fingerprint = {**data, "kind": "recovery_approve", "round_id": round_id, "actor_id": actor.pk}
    if original := audit_replay(action_id, fingerprint):
        return original
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
        if round.state == "FINALIZED":
            require_staff_permission(actor, "publish_results")
        payload = read_bundle(proposal.payload["signed_bundle"], round)
        restore_missing(round, payload)
        from .results import build_preview

        preview = build_preview(round, database_now())
        if preview["evidence_gaps"]:
            raise ApiProblem("evidence_gap", " ".join(preview["evidence_gaps"]), 409)
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


@transaction.atomic
def evidence_page(round_id, actor, kind, cursor=None, limit=200):
    require_result_view(actor)
    round = locked_round(round_id)
    queries = round_queries(round)
    if kind not in queries:
        raise ApiProblem("invalid_request", "Choose a supported evidence export type.")
    if type(limit) is not int or not 1 <= limit <= 500:
        raise ApiProblem("invalid_request", "Export limits must be from 1 to 500.")
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
