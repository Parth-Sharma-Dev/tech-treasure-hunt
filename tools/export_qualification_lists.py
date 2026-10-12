"""Run through the deployed Django shell; export four lists without database writes."""

import json

from competition.models import ResultSnapshot, Round, Team
from django.core.management.base import CommandError
from django.db import connection, transaction


def final_snapshot(number):
    round = Round.objects.filter(number=number, is_demo=False).order_by("-attempt_no").first()
    if round is None or round.state != Round.State.FINALIZED:
        raise CommandError(f"Latest real Round {number} must be FINALIZED.")
    snapshot = ResultSnapshot.objects.filter(round=round).order_by("-revision").first()
    if snapshot is None or snapshot.status != "FINAL":
        raise CommandError(f"Latest real Round {number} needs a published FINAL snapshot.")
    return snapshot


def build_lists():
    with transaction.atomic():
        # All queries observe the same snapshot, even during concurrent publication.
        with connection.cursor() as cursor:
            cursor.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
        r1 = final_snapshot(1)
        r2 = final_snapshot(2)
        published_q1 = set(r1.qualifier_codes)
        q2 = set(r2.qualifier_codes)
        if len(published_q1) not in (45, 50) or len(published_q1) != len(r1.qualifier_codes):
            raise CommandError("Expected 45 or the original 50 published Round 1 qualifiers.")
        entries1 = {row["team_code"]: row for row in r1.ranked_entries}
        entries2 = {row["team_code"]: row for row in r2.ranked_entries}
        if not published_q1 <= entries1.keys():
            raise CommandError("Round 1 qualifiers are missing from published standings.")
        candidates = sorted(
            (entries1[code] for code in published_q1),
            key=lambda row: (
                -row["score"],
                row["tie_time_ms"] if row["tie_time_ms"] is not None else 0,
                row["team_code"],
            ),
        )
        # Preserve an already published 45; reduce an old 50 using the requested tie order.
        q1 = {row["team_code"] for row in candidates[:45]}
        if not q2 <= q1:
            raise CommandError(
                "Round 2 qualifiers include teams outside the reduced Round 1 top 45: "
                + ", ".join(sorted(q2 - q1))
                + ". Review these results before exporting."
            )
        if not q2 <= entries2.keys():
            raise CommandError("Published qualifier lists do not match the round entrants.")
        if not entries2.keys() <= published_q1:
            raise CommandError("Round 2 final standings include teams outside Round 1 qualifiers.")
        names = dict(Team.objects.filter(is_demo=False).values_list("code", "name"))
        if not (entries1.keys() | q1 | q2) <= names.keys():
            raise CommandError("Published results reference missing or demo teams.")

        def rows(codes, entries):
            # Retain published display order; qualification membership is determined above.
            ordered = [code for code in entries if code in codes]
            ordered += sorted(codes - set(ordered))
            return [
                {
                    "team_code": code,
                    "team_name": entries.get(code, {}).get("team_name", names[code]),
                }
                for code in ordered
            ]

        return {
            "round_1_disqualified": rows(entries1.keys() - q1, entries1),
            "round_2_qualified": rows(q1, entries1),
            # Include qualifying entrants absent from Round 2's published standings.
            "round_2_disqualified": rows(q1 - q2, entries2),
            "round_3_qualified": rows(q2, entries2),
        }


if __name__ == "__main__":
    try:
        print(json.dumps(build_lists(), indent=2, ensure_ascii=False))
    except CommandError as error:
        raise SystemExit(str(error)) from error
