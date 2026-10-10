# Round 1: local operation and recovery

Updated 10 October 2026. Current codes use six ASCII letters/digits, case-insensitively. Frozen legacy attempts retain four-digit behavior; see [current rule changes](RULE_UPDATES_20261010.md). Use synthetic teams and clues for rehearsals. This describes implemented Round 1 functionality; production provisioning, actual roster/content verification and physical event drills are separate release work. [M10 recovery](EVIDENCE_RECOVERY.md) extends signed checkpoints and independent reconciliation to Rounds 2–4 while retaining this paper workflow.

## Entry points and roles

| Page | Purpose |
|---|---|
| http://127.0.0.1:5173/admin/ | Draft missions, independent verification, rule approval and marking READY |
| http://127.0.0.1:5173/staff/rounds | Open lobby, start, pause, resume, extend and end online play |
| http://127.0.0.1:5173/staff/results | Publication, incidents, corrections, paper reconciliation and recovery |
| http://127.0.0.1:5173/login | Team login; the dashboard links into the current Round 1 page |

`DEMO-content` prepares content and operates rounds/proposes reviews. `DEMO-verifier` independently verifies evidence and publishes results. Use separate browser profiles. Staff status alone does not grant competition permissions. Private credentials remain in `.local`; do not commit them.

The database round ID in URLs differs from the round number and attempt number. Choose the intended attempt on every organizer screen. New participant play uses the latest Round 1 attempt in the team's demo/live cohort; historical decisions, receipts and published results remain readable.

## Run the normal flow

1. Prepare all draft missions/settings, including six-character answers and the approved mission count, duration, capacity, owners, advancement count and policies.
2. A different verifier verifies competitive missions and approves the draft rules.
3. The controller uses **Validate and mark approved rounds READY** in the Rounds admin list.
4. On `/staff/rounds`, **Round action → Open lobby** appears only for a READY online round. Supply a reason and click **Apply: Open lobby**.
5. In LOBBY, select **Start round** and apply it with a new reason. The shared active clock starts once for all teams.
6. Teams sign in, click **Open Round 1**, and use a mission QR link or the **Mission fallback code** input. They explicitly open the mission, then submit its six ASCII letters or digits. Preserve leading zeros.
7. Pause/resume excludes frozen time from the clock, cooldown and answer quota. End closes the attempt permanently through ordinary controls. A FROZEN round can be ended directly.
8. After ENDED, select the attempt on `/staff/results`. Propose provisional results with a public summary. A different reviewer checks evidence and publishes them.
9. Resolve material incidents and wait the full appeal interval. Supply reserve-clue order/evidence for a cutoff tie. Independently propose/approve final results.

Published results remain accessible after play closes. Private drafts, proposed standings and supporting references remain staff-only. **Retry same results action** or **Retry same action** preserves the original UUID/payload after an uncertain write; do not invent another request to recover an unknown outcome.

To persist expired online or paper clocks:

```powershell
.venv/Scripts/python backend/manage.py end_expired_rounds --actor DEMO-content
```

Use new draft attempts for ordinary reruns. The one-off database reset previously requested for local testing is not a supported event-day reset operation.

## Reviewed score corrections

Use **Reviewed score corrections** on `/staff/results`. Prefer pausing online play before preparing a correction so new submissions do not stale the reviewed evidence.

1. Select a competitive mission and either **Accept an alternate answer** or **Void this mission**.
2. For an alternate answer, supply four digits. Enter a private reason, a participant-facing summary and private supporting evidence references.
3. Click **Propose score correction**. A material incident is created; this does not immediately change points.
4. A different verifier expands the proposal, checks the original evidence and confirms independent review.
5. Approve the correction, or reject it with a reason. Stale proposals can be rejected; recreate them against the current evidence before approval.

Alternate answers reclassify only originally evaluated wrong answers with matching answer evidence, including evaluated paper answers. Cooldown, quota-blocked, paused and late requests do not become eligible retroactively. The earliest eligible acceptance supplies the effective completion time; there is still at most one point per team/mission.

Voids preserve original decisions, completions and receipts while removing current credit and the mission from the maximum score. Rankings and the last-counted-completion tie time are recalculated. Original accepted replays remain accepted historical evidence.

A post-final correction additionally requires publication permission and explicit **Supersede final results** confirmation. Approval appends a provisional snapshot, preserves the old final snapshot, clears current qualifiers and starts a new appeal window. A new reviewed final publication is required.

If dependent rounds have already started, the reviewer must explicitly acknowledge progression impact. Active dependent play is paused and material qualification-impact incidents block progression pending separate adjudication. This does not automatically repair later-round scores.

## Irreversible paper fallback

Paper activation is a two-person decision, not a pause or an automatic outage response.

1. Pause the online round while active budget remains.
2. On the results desk, assign every active team to a paper desk and reference clock checks, online-writer isolation and the incident record.
3. **Propose paper activation**; a different verifier checks and approves the evidence.
4. Independent approval records the authoritative official start and end. Remaining active budget is carried over; paper time starts at approval. Do not begin scored paper work before approval or backdate its start.
5. Online scoring is permanently disabled for this attempt, across all browsers. Teams follow their assigned desks.
6. Preserve numbered original slips. Record team, mission, assigned desk, official timestamp, answer (except slips blocked without evaluation) and supporting evidence.
7. Propose each slip and have a different verifier approve it. Reconcile each team/mission in official chronological order. Import time does not determine scoring time.
8. Only one answer may be evaluated per team/mission per 60 active seconds. Additional attempts or already completed missions are recorded as blocked. Wrong, blocked and accepted slips remain evidence; accepted slips project at most one completion.
9. **End paper play** on the results desk, or persist its expired deadline using the expiry command. Reconcile remaining slips before final results; reject stale/unneeded paper proposals explicitly.

There is no return to online play or ordinary paper budget extension. See the [paper slip template](templates/PAPER_SLIP.md). References attest to retained physical evidence; the website does not prove that physical staffing, clocks or network isolation were correctly exercised.

## Signed exports and receipt checks

After ending/persisting the round, **Download signed round checkpoint** produces a private signed inventory and reconciliation bundle. This is signed, not encrypted: retain it privately and separately from the database backup. Preserve the original Django and answer-signing secrets separately.

Per-type exports are bounded to 200 rows by default, at most 500. Follow `next_cursor` until it is null; restart if evidence changes mid-export. JSON exports carry the full signed page manifest. `?format=csv` supplies spreadsheet-safe cells, an inventory-digest header and a next-cursor header. A CSV page is not a complete reconciliation bundle.

Browser bundles are limited to 10,000 records and 8 MB of signed content. For a larger ended round, capture an authorized local checkpoint:

```powershell
.venv/Scripts/python backend/manage.py export_round_evidence --round 1 --actor DEMO-content --output .local/round1-checkpoint.json
```

Existing export paths are never overwritten. Receipt files downloaded by teams contain response objects; each accepted object's `receipt` value is the signed token. **Verify retained signed receipts** accepts up to 100 tokens per request and distinguishes verified, invalid, conflicting and missing-decision evidence. A valid receipt with no stored decision is a coverage gap, not permission to invent an answer history.

## Backup and isolated restore

PostgreSQL 18 client tools must be on PATH. Keep dumps and manifests private, outside Git.

```powershell
.venv/Scripts/python backend/manage.py backup_competition --output .local/competition-checkpoint.dump
.venv/Scripts/python backend/manage.py restore_competition --backup .local/competition-checkpoint.dump --database tth_recovery_rehearsal --actor DEMO-content
```

Restore requires a new `tth_recovery_*` name and checks the signed archive checksum. It refuses an existing target or the current database, leaves the source untouched, revokes all restored team sessions, increments session versions and records recovery incidents. A failed recovery database is retained for inspection; the tool does not drop it.

To inspect a restored copy, use separate terminals and browser context. Do not overwrite the working `.env`:

```powershell
# Terminal A, repository root; settings apply to this terminal only.
$env:POSTGRES_DB = 'tth_recovery_rehearsal'
$env:DJANGO_CSRF_TRUSTED_ORIGINS = 'http://127.0.0.1:5174'
.venv/Scripts/python backend/manage.py migrate
.venv/Scripts/python backend/manage.py runserver 127.0.0.1:8001

# Terminal B, frontend directory.
$env:TTH_BACKEND_URL = 'http://127.0.0.1:8001'
npm.cmd run dev -- --port 5174
```

Use http://127.0.0.1:5174 for the recovery copy. Closing these terminals leaves the original environment file unchanged.

On that copy, stop/persist play before reconciliation. Upload the retained signed ended-round checkpoint to **Evidence exports and recovery**, supply references, and propose reconciliation. This revokes any newly allocated cohort sessions and creates a material incident. A different verifier reviews missing/changed/additional inventories and approves reconciliation. Recovering finalized results also requires publication permission.

Recovery appends exact missing signed evidence and reconstructs checkpoint projections/clock state under locks. It refuses conflicting immutable records or newer unbacked evidence, preserves current team status, restores database ID sequences and does not silently reactivate sessions. An incomplete/conflicting checkpoint remains blocked; retain both copies and gather newer evidence.

Signed checkpoints prove only their recorded inventory. Entirely lost records beyond the latest checkpoint need other retained exports/receipts and an independently reviewed coverage disposition. Use the [recovery checklist](templates/RECOVERY_CHECKLIST.md). Restored baseline incidents also require explicit independent closure after coverage is resolved; importing a bundle does not automatically certify every outage interval.

## Current boundaries

The implemented local Round 1 flow includes native scoring, publication, corrections, paper reconciliation and recovery tooling. M9 added reviewed roster administration; M10 added later-round recovery. Printable QR-card tooling remains separate work; Django admin's Teams/evidence sections remain read-only. Production deployment, actual content/route checks, real device/camera checks, physical paper drills and deployed capacity certification are not established by synthetic local acceptance.
