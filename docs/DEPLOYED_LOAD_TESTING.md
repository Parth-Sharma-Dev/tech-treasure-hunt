# Load-test the deployed event before opening participant access

Use the actual App Service plan, private PostgreSQL connectivity, Blob storage and
public website hostname. Point the deployment temporarily at a **new isolated
pre-play database copy**. Keep the original and earlier mock evidence intact.
Close public participant access during the rehearsal and record original settings.
Use the real workload path through Front Door/WAF if already deployed. Direct
Azure-host tests do not certify an edge/WAF configuration introduced afterward.

## Prepare the database copy

1. Finish the official 110-team roster and content on the original while DRAFT;
   retain a private clean backup. Create the load-test copy from that clean state.
2. On the copy, independently approve/start the load-test Round 1 using ordinary
   controls. Use correct real-cohort teams and record its **database ID**. Copy a
   released image mission's token privately if you want to test Blob reads too.
3. Revoke inherited participant sessions **on the copy only**, so each generator
   team can log in once. Keep staff sessions/verification separate. The current
   one-browser rule intentionally rejects additional independent team logins.
4. Keep the credentials CSV locally, with `Team ID` and `Password` columns.
   Additional registration columns are allowed. Never include staff passwords.
   Retain leading zeros; do not convert IDs through numeric spreadsheet parsing.

The included standard-library Python runner is
[`tools/load_deployment.py`](../tools/load_deployment.py). It uses genuine CSRF,
password login, cookies, dashboard/me/score polling and optional mission/image
reads; it logs out its team sessions afterward. It does not execute staff controls.
Reports contain aggregate counts/latencies/statuses, not passwords, answers or
HTTP bodies. It requires explicit confirmation of the isolated database, but
cannot independently detect which remote database your website is using.
The runner now checks one team's login, visible database round IDs and state
before starting the roster ramp, then logs out the preflight session. Wrong round
numbers/IDs or an unavailable session stop here. Reports distinguish application
error codes from transport error classes without printing private response data.

If an interrupted run leaves active test sessions, use the content administrator's
**Team sessions** page (`/admin/competition/teamsession/`) and **Revoke selected stale
browser sessions** for the abandoned sessions, identified by team and run-time
timestamps. Preserve legitimate participant sessions. A timeout can leave a
server-side login active even though the generator did not receive its response.

For the prepared database, the previously observed R1 database ID was **6**, not
the round number **1**. Always verify on the selected copy:

```sh
python manage.py shell -c "from django.db import connection; from competition.models import Round; print(connection.settings_dict['HOST'],connection.settings_dict['NAME']); print(list(Round.objects.filter(number=1,is_demo=False).values('id','attempt_no','state')))"
```

## Run progressively from your computer

From the repository root in PowerShell, replace URL, CSV path and R1 database ID.
Use the currently working public hostname. Each report needs a new filename.

```powershell
.venv/Scripts/python tools/load_deployment.py --base-url https://YOUR_WEBSITE_HOST --credentials .local/private-load-credentials.csv --round-id YOUR_R1_ID --teams 10 --duration-seconds 120 --ramp-seconds 20 --confirm-isolated-database --report .local/load-reports/smoke-10.json
```

Then 50 teams:

```powershell
.venv/Scripts/python tools/load_deployment.py --base-url https://YOUR_WEBSITE_HOST --credentials .local/private-load-credentials.csv --round-id YOUR_R1_ID --teams 50 --duration-seconds 180 --ramp-seconds 45 --confirm-isolated-database --report .local/load-reports/ramp-50.json
```

Then all 110, held for ten minutes:

```powershell
.venv/Scripts/python tools/load_deployment.py --base-url https://YOUR_WEBSITE_HOST --credentials .local/private-load-credentials.csv --round-id YOUR_R1_ID --teams 110 --duration-seconds 600 --ramp-seconds 60 --confirm-isolated-database --report .local/load-reports/full-110.json
```

Append `--mission-token YOUR_IMAGE_MISSION_TOKEN` to test explicit open, image
metadata and periodic private PNG reads. The token is a navigation identifier,
not a collectible answer code. Make sure the mission belongs to the exact LIVE
Round 1 attempt selected on the copy.

For **double polling load**, repeat 110 teams with `--poll-seconds 7.5` and a new
report filename. This models twice the normal request frequency with 110 sessions;
it is not 220 distinct teams or browsers. Actual frontend polling is randomized
around 15 seconds. For a separately approved stress test, use `--poll-seconds 1`
for 60 seconds to identify overload. Do not confuse stress failure with normal
capacity failure. Test the campus shared-IP route without weakening normal
authentication/rate controls.

## Submission burst and receipt replay

Use another clean isolated copy (previous claims remain exclusive). Add a private
`Load Code` column to the CSV containing **one different unclaimed pool code per
team**; 110 unique first claims fit the current 168-code pool. Use a LIVE mission
and append `--mission-token TOKEN --submit --ramp-seconds 0` to the 110-team run.

Each team submits once and immediately replays the same UUID. The runner checks
accepted outcome and stable decision/points/receipt. Verify on the test database
that the run created exactly one credited claim per team and no duplicate credit.
A separate two-team same-code collision test must produce one owner only; do not
use shared codes for the runner's accepted-write scenario.

## Watch Azure during every run

Open App Service **Monitoring → Metrics** and watch CPU, memory, request count,
HTTP response time and server errors. On PostgreSQL watch CPU, active connections,
memory/storage/IO as available, and query/lock behavior through your existing
database monitoring. Watch Blob failures and Front Door/WAF logs when applicable.
Keep a staff browser open to verify controls/results remain responsive under load.

The runner proposes API read latency goals p95 under two seconds and p99 under
five, all requested teams authenticated, no functional failures, and HTTP error
rate under 1%. It fails fast on invalid authentication/session/round state instead
of generating anonymous traffic that would falsely certify capacity. Initial
login, open, submit/replay and logout latencies are reported separately; inspect
those too rather than treating a read-only PASS as a complete event certificate.
Ensure the machine/network generating load is not the bottleneck.

If normal-load CPU remains saturated, memory is near exhaustion, login/API
requests fail or database connections/locks accumulate, investigate and scale
the relevant resource, then rerun the same profile. Increasing web instances
does not automatically solve database contention. Record the exact SKU/instance
count, application revision, peak traffic and observed thresholds.

## Finish and verify recovery

Retain reports and test evidence privately. Return App Service to the original
database configuration, revoke obsolete copied authentication/session access and
check image references/objects, health and clean round/roster state. Discard saved
load/mock actions from test browsers. A redeployed ZIP does not undo database
claims; never reset live evidence to clean up a load test.

The runner's real HTTP read and independent-code replay modes passed isolated
PostgreSQL/Django integration checks. Azure capacity is still unmeasured until
you execute and retain these deployed reports.

For a managed alternative, Azure Load Testing can use an authenticated JMeter
script with CSV credentials and CSRF/cookie handling; a URL-only health test
does not exercise these authenticated workflows. See
[App Service load-testing guidance](https://learn.microsoft.com/en-us/azure/load-testing/concept-load-test-app-service)
and [authenticated endpoints](https://learn.microsoft.com/en-us/azure/load-testing/how-to-test-secured-endpoints?tabs=portal).
