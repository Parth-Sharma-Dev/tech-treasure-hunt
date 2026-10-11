"""Run through Django shell/runpy on Azure; export QR navigation links, not answers.

Optional environment variables: TTH_QR_BASE_URL, TTH_QR_ROUND_ID, TTH_QR_ACTOR,
TTH_QR_OUTPUT. No new application deployment is needed to run this script.
"""

import csv
import os
from pathlib import Path
from urllib.parse import quote, urlsplit

from competition.models import Mission, Round
from competition.rules import require_staff_permission
from django.contrib.auth import get_user_model
from django.core.management.base import CommandError


def export_links(base_url, round_id, actor_name, output):
    base_url = base_url.rstrip("/")
    parsed = urlsplit(base_url)
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.path
        or parsed.query
        or parsed.fragment
    ):
        raise CommandError(
            "Use an HTTPS website origin without credentials, path, query or fragment."
        )
    actor = get_user_model().objects.filter(username=actor_name).first()
    if actor is None:
        raise CommandError("Content staff account not found.")
    require_staff_permission(actor, "prepare_content")
    round = Round.objects.filter(pk=round_id, number=1, is_demo=False).first()
    if round is None:
        raise CommandError("Choose the database ID of the intended real Round 1.")
    missions = list(
        Mission.objects.filter(round=round, is_practice=False).order_by("public_id")
    )
    if not missions:
        raise CommandError("This Round 1 has no competitive missions.")
    path = Path(output)
    path.parent.mkdir(parents=True, exist_ok=True)
    # Exclusive creation preserves existing QR packs. UTF-8 BOM helps Excel open CSVs.
    with path.open("x", encoding="utf-8-sig", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(["mission_id", "mission_url", "fallback_code"])
        for mission in missions:
            writer.writerow(
                [
                    mission.public_id,
                    f"{base_url}/missions/{quote(mission.token, safe='')}",
                    mission.fallback_code,
                ]
            )
    path.chmod(0o600)
    warnings = {
        "unavailable": sum(not m.available for m in missions),
        "unverified": sum(m.verified_at is None for m in missions),
        "voided": sum(m.is_void for m in missions),
    }
    return path, len(missions), warnings


def main():
    base = os.environ.get(
        "TTH_QR_BASE_URL",
        "https://techtreasurehunt-g2ashqezbqcrfvdj.centralindia-01.azurewebsites.net",
    )
    output = os.environ.get(
        "TTH_QR_OUTPUT", "/home/site/private-transfer/round1-mission-links.csv"
    )
    path, count, warnings = export_links(
        base,
        int(os.environ.get("TTH_QR_ROUND_ID", "6")),
        os.environ.get("TTH_QR_ACTOR", "parth"),
        output,
    )
    print(f"Exported {count} mission links to {path}. No database records changed.")
    if any(warnings.values()):
        print(f"Check before printing the final QR pack: {warnings}")
    # Only requested navigation URLs/fallback codes are shown, no clues/locations/answers.
    with path.open(encoding="utf-8-sig", newline="") as stream:
        print(stream.read())


if __name__ == "__main__":
    main()
