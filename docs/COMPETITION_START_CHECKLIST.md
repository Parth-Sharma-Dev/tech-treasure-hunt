# Competition start checklist: Round 1 and Round 2

Use this against the deployed website, not localhost. Tick a box only after checking it. Record unfinished items and the responsible person before opening play.

Primary participant URL: **https://techtreasurehunt.in**

Content/controller: **parth**. Independent verifier: **verifier**.

## 1. Confirm the production environment

- [ ] App Service is `techtreasurehunt` in `tth-event-rg` and is running.
- [ ] Django uses server `tth-event-db-parth.postgres.database.azure.com`, database `treasure_hunt`; it is not pointed at a mock/load-test database.
- [ ] The intended release includes staff MFA, official roster import and the final R1/R2 rules.
- [ ] All migrations are applied: `python manage.py migrate --check` exits successfully.
- [ ] No deployment, restart, database switch or load test is scheduled during the competition.
- [ ] App Service Always On is enabled. Working runtime/startup/worker settings are retained.
- [ ] PostgreSQL and private Blob storage are reachable from the running application.

In App Service SSH, from the active directory containing `manage.py` with `antenv` activated, run this read-only inspection:

```bash
python manage.py shell <<'PY'
from django.db import connection
from competition.models import Round, Team, Mission
print('DB:', connection.settings_dict['HOST'], connection.settings_dict['NAME'])
print('Active official teams:', Team.objects.filter(is_demo=False, status='ACTIVE').count())
print('Real rounds:', list(Round.objects.filter(is_demo=False).values(
    'id', 'number', 'attempt_no', 'state')))
for r in Round.objects.filter(number=1, is_demo=False):
    missions = Mission.objects.filter(round=r, is_practice=False)
    print('R1', r.pk, 'missions:', missions.count(),
          'available:', missions.filter(available=True).count(),
          'verified:', missions.filter(verified_at__isnull=False).count())
PY
python manage.py migrate --check
```

Expected current round IDs: **R1 = 6, R2 = 7**. Confirm the output; a database ID is not a round number. Counts alone do not prove content readiness.

## 2. Domain, browser and staff access

- [ ] `https://techtreasurehunt.in` opens with a valid certificate and no browser security warning.
- [ ] `/api/health` responds successfully; `/login`, dashboard and staff pages work through this domain.
- [ ] Azure allowed hosts and CSRF trusted origins include the custom domain. A real staff POST succeeds without a CSRF error.
- [ ] All published links and QR cards use the chosen primary hostname consistently.
- [ ] The Azure hostname remains allowed for health checks and retained older links.
- [ ] `parth` and `verifier` can both sign in with MFA using separate browser profiles/devices.
- [ ] Their required permissions work: content/control for parth, independent verification/publication for verifier.
- [ ] Recovery codes are retained privately by their owners; authenticator devices are charged and clocks are correct.
- [ ] Private credential CSVs, answer banks, backups and recovery codes are not in public assets or shared participant folders.
- [ ] Participant clue pages/responses do not reveal riddle destination answers, unclaimed hunt codes or private staff evidence.

## 3. Official roster and sessions

- [ ] Exactly **110 intended official teams** are ACTIVE, `is_demo=False`, with four members each.
- [ ] Team IDs match the official CSV, including leading zeros. Demo/mock accounts are excluded from the official count.
- [ ] Credentials were imported through Django password hashing and distributed privately.
- [ ] Stale sessions from previous load tests have been reviewed and revoked, especially sessions whose logout failed.
- [ ] At least one actual team can log in, see Round 1 and sign out successfully through the custom domain.
- [ ] Teams know that only **one active browser session per team** is allowed. Sign out before switching browsers or hostnames.
- [ ] A help-desk operator can identify a team and revoke a genuinely stale session without changing its password or score.
- [ ] Teams are invited to sign in gradually before the start; everyone is told that login alone does not start the round clock.

Do not revoke every session once legitimate participants have started signing in.

## 4. Final approved rules

| Setting | Round 1 | Round 2 |
|---|---|---|
| Delivery | ONLINE_HUNT | EXTERNAL / Wayground |
| Active duration | 60 minutes / 3,600,000 ms | 60 minutes / 3,600,000 ms |
| Advancement | 50 teams | 20 teams |
| Appeal window | 5 minutes | 5 minutes |
| Content | 25 missions, 168 independent hunt codes | 30 questions |
| Ranking | Accepted code count, then original last-claim active time | Raw Wayground Score, then lower answering duration |

- [ ] The deployed attempt uses these values and the approved current rules JSON: [R1](examples/round1-final-rules.json), [R2](examples/round2-final-rules.json).
- [ ] Actual venue, route, help contacts, timetable, allowed tools and accessibility arrangements match participant instructions.
- [ ] The independent verifier has approved the current rules; there are no stale approvals.
- [ ] Both intended rounds are READY before their release, with no outstanding readiness blockers.
- [ ] Round 1 is available to all active official entrants. Round 2 activity is restricted to finalized R1 qualifiers, even if its card is visible to everyone.
- [ ] Exact qualification-boundary ties have a prepared supervised reserve procedure and evidence recorder.

Do not rerun draft configuration/import commands on released rounds or reset their states directly in the database.

## 5. Round 1 content and physical route

- [ ] All **25 intended missions** exist, are complete, available and independently verified.
- [ ] The 13 riddle clues match the organizer's intended wording and private destinations.
- [ ] All 12 intended image/symbol clues have their actual images; no empty placeholders remain.
- [ ] Image alternative text is useful and does not disclose the destination answer or collectible code.
- [ ] Private image previews work. Actual image retrieval through a participant session was checked in the rehearsal.
- [ ] Images are already uploaded before release; READY/released content cannot be edited in place.
- [ ] Each mission has an assigned responsible volunteer and the correct physical QR placement.
- [ ] QR cards were generated from actual mission URLs/tokens, not guessed IDs; labels and mission fallback codes match the corresponding mission.
- [ ] Every printed QR was scanned on a phone and checked for the correct destination URL; fallback navigation was checked in the rehearsal.
- [ ] Cards are readable, weather protected where needed, reachable and inside the approved safe route.
- [ ] Collectible hunt-code slips match the private pool exactly, including punctuation and leading zeros. Mission fallback codes are not collectible hunt codes.
- [ ] Volunteers understand exclusive ownership: each hunt code can be claimed by only one team, and each team can claim at most three, one point each.
- [ ] Participants understand that 168 codes cannot provide three codes to every one of 110 teams; scarcity is part of the approved format.
- [ ] Participants know to explicitly open a mission, retain accepted receipts/keywords and avoid repeatedly guessing codes.

Do not consume official hunt codes as a last-minute submission test.

## 6. Round 2 Wayground preparation

- [ ] The genuine 30-question quiz, answer key and reserve question are ready and independently checked.
- [ ] The Wayground host account, venue equipment, internet and session settings are ready.
- [ ] Player naming/registration identifies each eligible team unambiguously by its official team ID.
- [ ] Volunteers know the supervision/device policy and how teams retain required R1 keywords before the session.
- [ ] The organizer can download the original `.xlsx` report containing `Participant Data`, raw `Score` and `Total Time Taken`.
- [ ] Staff can access `/staff/scores` and `/staff/results`; both operators understand mapping, dry-run, independent commit and publication.
- [ ] Every eligible entrant will have report coverage or an explicitly reviewed disposition; no invented scores or synthetic mock workbook will be used.
- [ ] R2 will open only after independently finalized R1 qualification, not merely provisional results.

## 7. Capacity, backup and outage readiness

- [ ] Latest evidence is recorded: 110 logins and 12,144 successful polling requests, with slow tail latency and 13 failed logouts in the reported run.
- [ ] The organizer understands that the full write load test was skipped; submission capacity has not been certified by that read-only run.
- [ ] No load generator is still running. Private test reports are retained for troubleshooting.
- [ ] Azure Log stream and App Service CPU/memory metrics are open; PostgreSQL CPU/connections/storage are monitored.
- [ ] An operator can pause/resume through `/staff/rounds` and communicate an outage instruction promptly.
- [ ] A fresh private database backup/checkpoint is retained before opening play, with a known timestamp and checksum where available.
- [ ] Database credentials/signing secrets and private image objects are retained securely; a database dump alone does not contain Blob image bytes.
- [ ] Recovery responsibilities and the latest recoverable checkpoint are understood. Any unperformed recovery rehearsal is explicitly recorded.
- [ ] An independent-code outage uses pause and reviewed recovery; volunteers will not improvise the legacy mission-based paper-scoring workflow.
- [ ] On uncertain write outcomes, staff retry the saved action/UUID rather than creating another action blindly.

Deferred work must be recorded honestly: **Front Door/WAF and origin restrictions are not complete merely because the custom domain works.**

## 8. Final desk check immediately before start

- [ ] Controller and verifier are present, signed in and agree the selected real attempt is correct.
- [ ] No unresolved material incident, qualification issue or pending review blocks the intended start.
- [ ] Volunteers are at their locations; participants know the route, help desk and common start/end instructions.
- [ ] Enough teams have signed in successfully; stale-session problems are handled before the clock starts.
- [ ] Open the R1 lobby through staff controls, confirm participants see it, then use **Start round** once at the announced time.
- [ ] Confirm the state and shared 60-minute clock after starting. If the request outcome is uncertain, inspect state before retrying the saved action.

## 9. End and advance correctly

- [ ] End Round 1 through staff controls; retain accepted receipts and evidence.
- [ ] Propose and independently publish provisional results; resolve appeals and cutoff ties; wait the full five-minute appeal window.
- [ ] Independently publish final **50 R1 qualifiers** before opening R2.
- [ ] After R2 ends, retain the genuine report, map all rows, dry-run and independently commit the intake.
- [ ] Publish provisional R2 results, resolve blockers and wait five minutes, then independently publish final **20 qualifiers**.
- [ ] Retain private round checkpoints, reports and incident records after each round.

## Organizer sign-off

- Controller: __________________  Time: __________________
- Independent verifier: __________________  Time: __________________
- Remaining items / owner / decision: ______________________________________
- Explicitly accepted limitations: skipped write load test, incomplete recovery rehearsal if applicable, deferred Front Door/WAF/origin restrictions, and any other unchecked item.

References: [final release settings](FINAL_R1_R2_RELEASE.md), [staff MFA](STAFF_MFA.md), [mission QR export](MISSION_QR_EXPORT.md), [Wayground operations](EXTERNAL_ROUND_OPERATIONS.md), [recovery checklist](templates/RECOVERY_CHECKLIST.md).
