# Mission URL and fallback-code export in App Service SSH

This read-only export contains navigation URLs/fallback identifiers, not riddles,
answer locations, collectible codes or keywords. Use the exact original Round 1
database ID (currently 6). Choose the working final public hostname before printing
QRs; changing the hostname below does not change database tokens.

In the active application directory with `antenv` activated, paste:

```sh
python manage.py shell <<'PY'
import csv
from pathlib import Path
from urllib.parse import quote
from django.contrib.auth import get_user_model
from competition.models import Mission, Round
from competition.rules import require_staff_permission

BASE_URL = "https://techtreasurehunt-g2ashqezbqcrfvdj.centralindia-01.azurewebsites.net"
ROUND_ID = 6
OUTPUT = Path("/home/site/private-transfer/round1-mission-links.csv")

actor = get_user_model().objects.get(username="parth")
require_staff_permission(actor, "prepare_content")
round = Round.objects.get(pk=ROUND_ID, number=1, is_demo=False)
missions = list(Mission.objects.filter(round=round, is_practice=False).order_by("public_id"))
if not missions:
    raise RuntimeError("No competitive missions found for this round.")
OUTPUT.parent.mkdir(parents=True, exist_ok=True)
with OUTPUT.open("x", encoding="utf-8-sig", newline="") as stream:
    writer = csv.writer(stream)
    writer.writerow(["mission_id", "mission_url", "fallback_code"])
    for mission in missions:
        writer.writerow([mission.public_id,
                         f"{BASE_URL}/missions/{quote(mission.token, safe='')}",
                         mission.fallback_code])
OUTPUT.chmod(0o600)
print(f"Saved {len(missions)} missions to {OUTPUT}. No database records changed.")
print(OUTPUT.read_text(encoding="utf-8-sig"))
PY
```

The output lists one CSV row per competitive mission, including unavailable drafts,
so you can prepare labels before opening play. Verify the intended missions are
available and independently verified before distributing the final pack. Existing
output files are not overwritten; use a different OUTPUT filename for a new pack.

Make each QR encode the `mission_url` exactly. Print the mission ID and fallback
code as human-readable labels. Fallback codes navigate to missions; they are not
the six-character collectible codes. A scan does not bypass team login, live-round
eligibility or the explicit Open mission action.

A reusable standalone version is [tools/export_mission_links.py](../tools/export_mission_links.py).
If uploaded privately to App Service, run it without redeploying the application:

```sh
python manage.py shell -c "import runpy; runpy.run_path('/home/site/private-transfer/export_mission_links.py',run_name='__main__')"
```

Optional environment variables `TTH_QR_BASE_URL`, `TTH_QR_ROUND_ID`, `TTH_QR_ACTOR`
and `TTH_QR_OUTPUT` override the same defaults. The reusable exporter validates an
HTTPS origin and prints incomplete/voided mission counts before its CSV listing.
Its six isolated tests cover URL construction, private-field exclusion, permissions,
wrong-cohort rejection and preserving previous export files.
