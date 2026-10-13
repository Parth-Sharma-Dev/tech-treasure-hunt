"""Audited immediate Green Card publication, compatible with deployed older code.

Only the Round 4 appeal waiting period is waived by explicit organizer direction.
Other eligibility/evidence/independent-review checks remain enforced.
"""

import inspect
import os
import uuid
from contextlib import contextmanager


@contextmanager
def appeal_override(results, use_native):
    original = results.final_qualifiers
    if not use_native:

        def reviewed_override(round, preview, data, **_options):
            if round.number != 4 or preview.get("ranking_kind") != "GREEN_CARDS":
                raise ValueError(
                    "This appeal override applies only to Round 4 Green Cards."
                )
            amended = {
                **preview,
                "finalization_blockers": [
                    item
                    for item in preview["finalization_blockers"]
                    if item != "The published appeal window is still open."
                ],
            }
            return original(round, amended, data)

        results.final_qualifiers = reviewed_override
    try:
        yield
    finally:
        results.final_qualifiers = original


def publish(
    codes,
    reviewed=False,
    dry_run=True,
    maker_name="parth",
    verifier_name="verifier",
    force_legacy=False,
):
    from competition import results
    from competition.clock import control_round, database_now
    from competition.external_scores import commit_import, validate_import
    from competition.green_cards import SCHEMA, is_green_cards
    from competition.models import AuditEvent, Round, Team
    from competition.participant import round_eligible
    from competition.rules import require_staff_permission
    from django.contrib.auth import get_user_model
    from django.db import transaction

    if len(codes) != 5 or len(set(codes)) != 5:
        raise ValueError("Provide exactly five distinct full team IDs.")
    if not reviewed:
        raise ValueError(
            "The actual verifier must check the complete Green Card list first."
        )
    reason = "Organizer confirms five Green Card finalists; provisional and final publication requested now, with the appeal waiting period explicitly waived."

    def request(**data):
        return {"action_id": str(uuid.uuid4()), "reason": reason, **data}

    with transaction.atomic():
        users = get_user_model().objects
        maker, verifier = (
            users.get(username=maker_name),
            users.get(username=verifier_name),
        )
        require_staff_permission(maker, "control_round")
        require_staff_permission(verifier, "verify_evidence")
        require_staff_permission(verifier, "publish_results")
        if maker.pk == verifier.pk:
            raise ValueError("Maker and verifier must be different accounts.")
        round = (
            Round.objects.select_for_update()
            .filter(number=4, is_demo=False)
            .order_by("-attempt_no")
            .first()
        )
        if round is None or not is_green_cards(round) or round.advancement_count != 5:
            raise ValueError(
                "Use the approved real Round 4 Green Card attempt with cut five."
            )
        if round.state == "FINALIZED":
            final = results.latest_snapshot(round)
            if (
                final
                and final.status == "FINAL"
                and set(final.qualifier_codes) == set(codes)
            ):
                return {
                    "already_final": True,
                    "round_id": round.pk,
                    "qualifier_codes": final.qualifier_codes,
                }
            raise ValueError(
                "Finalized results differ; ordinary publication cannot replace them."
            )
        if round.state not in (
            "READY",
            "LOBBY",
            "LIVE",
            "FROZEN",
            "ENDED",
            "PROVISIONAL",
        ):
            raise ValueError(
                "Round 4 must be approved/READY or later; do not reset its state."
            )
        teams = list(Team.objects.filter(code__in=codes, is_demo=False))
        if len(teams) != 5 or any(not round_eligible(team, round) for team in teams):
            raise ValueError(
                "All five teams must be active real Round 3 FINAL qualifiers."
            )
        if round.state == "READY":
            control_round(
                round.pk,
                maker,
                request(action="open_lobby", expected_version=round.control_version),
            )
            round.refresh_from_db()
        if round.state == "LOBBY":
            control_round(
                round.pk,
                maker,
                request(action="start", expected_version=round.control_version),
            )
            round.refresh_from_db()
        if round.state in ("LIVE", "FROZEN"):
            control_round(
                round.pk,
                maker,
                request(action="end", expected_version=round.control_version),
            )
            round.refresh_from_db()
        batch = validate_import(
            round.pk,
            maker,
            request(
                schema_version=SCHEMA["version"],
                rows=[{"team_name": code} for code in codes],
                complete_list_confirmed=True,
            ),
        )
        if batch["errors"]:
            raise ValueError(f"Green Card intake errors: {batch['errors']}")
        commit_import(
            round.pk,
            verifier,
            request(batch_id=batch["batch_id"], evidence_confirmed=True),
        )
        native = (
            not force_legacy
            and "allow_open_appeal"
            in inspect.signature(results.propose_result).parameters
        )
        with appeal_override(results, native):
            for status in ("PROVISIONAL", "FINAL"):
                round.refresh_from_db()
                preview = results.build_preview(round, database_now())
                kwargs = {"allow_open_appeal": status == "FINAL"} if native else {}
                proposal = results.propose_result(
                    round.pk,
                    maker,
                    request(
                        status=status,
                        expected_version=round.control_version,
                        evidence_digest=preview["evidence_digest"],
                        evidence_confirmed=True,
                    ),
                    **kwargs,
                )
                published = results.approve_result(
                    round.pk,
                    verifier,
                    request(
                        proposal_id=proposal["proposal_id"], evidence_confirmed=True
                    ),
                    **kwargs,
                )
        if set(published["qualifier_codes"]) != set(codes):
            raise ValueError("Published qualifiers do not match the reviewed list.")
        AuditEvent.objects.create(
            actor=maker,
            action="round4_appeal_override",
            reason=reason,
            after={
                "round_id": round.pk,
                "snapshot_id": published["snapshot_id"],
                "qualifier_codes": published["qualifier_codes"],
                "verifier_id": verifier.pk,
            },
        )
        if dry_run:
            transaction.set_rollback(True)
        return {**published, "dry_run": dry_run, "appeal_wait_waived": True}


if __name__ == "__main__":
    import json

    from django.db import connection

    if (
        connection.settings_dict["NAME"] != "treasure_hunt"
        or connection.settings_dict["HOST"]
        != "tth-event-db-parth.postgres.database.azure.com"
    ):
        raise ValueError(
            "Stop: select the original production database before publishing."
        )

    print(
        json.dumps(
            publish(
                os.environ["TTH_R4_CODES"].split(),
                reviewed=os.environ.get("TTH_R4_REVIEW_CONFIRMED") == "1",
                dry_run=os.environ.get("TTH_R4_DRY_RUN", "1") == "1",
            ),
            indent=2,
        )
    )
