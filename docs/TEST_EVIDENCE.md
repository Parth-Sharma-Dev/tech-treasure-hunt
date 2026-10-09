# Local acceptance evidence

Recorded 7 October 2026. Scope: implemented Round 1 behavior using synthetic fixtures. Later-round competition, production hosting, real mission routes, actual rosters and physical device/paper drills are not certified here.

M7 participant portal validation was added on 8 October; the original Round 1 evidence below is retained as a dated record.

## Environment

| Component | Tested version |
|---|---|
| OS | Windows; PowerShell |
| Python | 3.13.13 |
| Django | 6.0.8 |
| PostgreSQL server / pg_dump | 18.6 |
| Node | 24.15.0 |
| pytest | 9.1.1 |
| Ruff | 0.16.9 |
| Playwright | 1.63.0, Chromium desktop and emulated Pixel 7 |

## Final validation

| Check | Outcome |
|---|---|
| Django system checks | Passed, no issues |
| Migration drift check | Passed, no changes detected |
| Ruff backend checks | Passed |
| Frontend TypeScript and Vite production build | Passed |
| Full backend suite with real-browser integrations enabled | **125 passed, 1 skipped**; skipped local load test was run separately |
| Full frontend Playwright suite | **58 passed** |
| Separate local HTTP contention test | **1 passed**, isolated PostgreSQL test database |
| pg_dump/restore rehearsal | Passed into a new recovery database; source preserved, all restored team sessions revoked |
| Running application health | Backend port 8000 and Vite proxy port 5173 both returned healthy |

Commands, from the repository root unless stated otherwise:

```powershell
.venv/Scripts/python backend/manage.py check
.venv/Scripts/python backend/manage.py makemigrations --check --dry-run
.venv/Scripts/python -m ruff check backend
npm.cmd --prefix frontend run build

$env:TTH_BROWSER_INTEGRATION = '1'
.venv/Scripts/python -m pytest backend -q -p no:cacheprovider

# In frontend:
npm.cmd run test:e2e -- --workers=2
```

The Windows sandbox denied access to pytest's existing temporary fixture directory during the initial full run. The final backend run used approved access and completed successfully. Ordinary tests use an isolated PostgreSQL database; browser integrations route requests to the isolated Django live server, not the application's database.

## Covered behaviors

- Approved draft rules, independently verified missions and READY freeze; repeatable unsigned demo seeding.
- CSRF-protected team login/logout, four-session contention, revoked-session/version checks and validated return links.
- Dashboard → Round 1 page; live-only fallback entry; paused/ended status; desktop/mobile layout checks.
- Explicit mission open, QR/fallback identity, four-digit answers with leading zeros, immutable decisions and signed receipts.
- Duplicate/cross-session answers, shared quotas/cooldowns, lock waits spanning deadlines, stale controls and lost-response recovery.
- Provisional/final publication, full appeal windows, cutoff ties, private/public evidence boundaries and two-person review.
- Alternate answers preserving original wrong/accepted decisions; effective timing rebuild; voided score/denominator; stale/rejected proposals.
- Explicit final supersession and renewed appeals; acknowledged downstream qualification impact and suspended dependent play.
- One-way paper activation, clock offsets, assigned desks, chronological slips, per-minute paper limits, duplicate rejection and preserved online evidence.
- Signed export inventories, bounded pagination, stale cursors, formula-safe cells, invalid/missing receipts and reviewed restoration of exact missing decisions/completions.
- New staff endpoints reject participants and require CSRF; recovery invalidates sessions and blocks unresolved qualification.

Two full browser integrations use actual Django HTTP/PostgreSQL: organizer start → team login → QR open → solve → pause → receipts/logout, and independent provisional → final publication/qualification.

## Local contention measurement

```powershell
$env:TTH_LOCAL_LOAD_TEST = '1'
$env:TTH_LOAD_TEAMS = '8'
$env:TTH_LOAD_SESSIONS = '4'
.venv/Scripts/python -m pytest backend/tests/test_round1_load.py -q -s -p no:cacheprovider
```

| Measurement | Result |
|---|---:|
| Synthetic teams | 8 |
| Browser sessions per team | 4 |
| Simultaneous submit requests | 32 |
| Subsequent authenticated state reads | 96 |
| Submit HTTP p95 | 2345.449 ms |
| State HTTP p95 | 2203.543 ms |
| Server ingress → database admission p95 | 291.341 ms |
| Effective completions | 8, exactly one per team |

The report is retained privately in `.local/round1-load-evidence.json`. This run measures local Django's test HTTP server under a synchronized burst. Admission latency includes application/lock time; it is not a separate SQL-lock-only measurement. It does not establish Render/free-tier capacity, production cold-start behavior or a real event cap. Production-scale k6/load testing remains a release gate once the target environment and team cap are supplied.

## Recovery rehearsal and retained artifacts

A custom PostgreSQL archive and signed checksum were captured before applying migrations 0007–0009. The archive was restored to `tth_recovery_round1_20261007`; both source/restored databases contained five rounds and the restored copy had zero active team sessions. A recovery incident was recorded. The separate copy and private archive remain available in `.local`; the working source Round 1 attempt remains READY.

The old checkpoint predates the new migrations. Migrate the separate copy before using the new review screens. Keep baseline recovery incidents material until retained evidence and any missing intervals are independently reviewed. Do not redirect participants to the recovery copy merely because the archive restored successfully.

## Remaining release checks

Supply and independently verify actual content, roster, capacity, route, owner and appeal policies. Validate real Android/iPhone QR handoff, campus/lab connectivity, physical slip/clock/writer-isolation procedures and deployed recovery/capacity. Real-roster administration, printable QR cards and later-round functionality remain separate planned work. Entirely missing records beyond the latest signed checkpoint require retained receipts/exports and human coverage review; synthetic tests cannot prove their absence.

## M7 portal regression — 8 October 2026

- Full backend suite with `TTH_BROWSER_INTEGRATION=1`: **133 passed, 1 skipped** (opt-in local load test).
- Full frontend desktop/mobile Chromium suite: **66 passed**.
- Django system/migration checks, Ruff and frontend TypeScript/Vite build: passed.
- New coverage: independent information publication; draft revisions preserving the last release; notice withdrawal; malformed contacts/schedules; reviewed-cohort binding; latest-attempt/foreign-cohort/Round 5 guards; expired activity; portal schedule/announcements/contacts; ineligible instruction redaction; retained result links.
- Migration 0010 applied after a signed local database backup. Existing Round 1 remains READY and other rounds remain DRAFT.

See [portal operations](PARTICIPANT_PORTAL.md). New portal endpoints were functionally validated; the earlier load measurement covers Round 1 state/submission traffic, not the new dashboard's deployed capacity. Actual information and later-round coding/scoring remain separately supplied/implemented.

## M8 coding regression — 8 October 2026

- Full backend suite with all real-browser integrations enabled: **148 passed, 1 skipped** (the opt-in local load test).
- Full desktop/mobile Chromium suite: **80 passed**.
- Frontend TypeScript/build, Ruff, Django system checks and migration drift checks passed.
- Native release tests enforce five category totals, verification, task freeze and no moving released content.
- Save/final tests cover expected revisions, UUID replay, assignment isolation, source confidentiality, permanent final locking, cutoff/no-submission outcomes and concurrent same-revision tabs (one acknowledgment, one conflict).
- Lab judging tests cover partial marks, invalid case IDs/source hashes, independent review, correct-task precedence, exact ties, final qualification and revised provisional appeals after changed marks.
- A third actual Django HTTP/PostgreSQL browser journey covers coding assignment, saved response, final lock, lab judgment, independent score review and provisional publication. The Round 1 integrations also passed; teardown now waits for in-flight routed requests to finish.
- Migrations 0011–0012 and unsigned demo preparation were applied after a signed private backup. Source Round 1 remains READY; Round 3 remains DRAFT with five unverified tasks and no fabricated qualification.

These tests use synthetic qualifying/grade evidence in isolated databases. Actual Round 2 import/publication remains M9; actual code evaluation happens in the lab, not the website. Native coding reconciliation manifests, deployed capacity and physical/network/toolchain checks remain later validation work. See [Round 3 operations](ROUND3_OPERATIONS.md).

## M9 external results and roster regression — 8 October 2026

- Full backend suite with all four actual-browser integrations enabled: **186 passed, 1 skipped** (the opt-in load test). A subsequent focused external suite covers the final fractional-faculty rounding change.
- Desktop/mobile Chromium: **94 passed** across the existing 80 checks and 14 new external/roster/faculty/Green Card checks. Frontend TypeScript/Vite build, Ruff, Django checks and migration drift checks passed.
- Round 2 tests cover canonical question credit, exact CSV headers/extra cells, unknown/ineligible teams, duplicates, explicit zeros, bounded finish time, private dry runs, atomic independent commits, UUID replay, stale intake, immutable source batches, appended corrections, global voids/recalculated maxima, renewed provisional appeals, common reserve-question cutoff decisions and final R3 eligibility.
- Round 4 tests cover approved panel profiles/slots, all three source sheets, finite/range/precision enforcement, retained private marks, weighted totals, separately rounded public averages, exact criterion sums for ties, missing-sheet rejection and provisional publication. A fractional technical average of 8.333 displays correctly while the weighted total uses the original sums and rounds to 70.333, avoiding premature rounding drift.
- Faculty tests cover consent/independent publication, unpublished/draft redaction, cohort binding and preservation of an approved profile during later edits. Browser checks cover own panel assignment, accessible faculty placeholders and deferred Round 5 after Green Cards.
- Roster tests cover independently reviewed creation/import, duplicate/account conflicts, locked identities after release, stale/rejected proposals, withdrawal, session-version/revocation, post-final qualification-impact incidents and credential issuance without plaintext audit passwords.
- A fourth actual Django HTTP/PostgreSQL browser journey covers external CSV dry run → independent source commit → independently approved provisional publication → participant hand-in/score results, followed by real-cohort roster creation → independent approval → credential issuance. All fixtures use an isolated test database. Existing R1 gameplay/publication and native R3 lab-review journeys also passed.
- Migration 0013 applied after a signed private source database backup. Unsigned external demo schemas were prepared in existing R2/R4 DRAFT attempts, preserving configured/released rounds and small demo advancement counts. Source R1 remains READY; R3 remains DRAFT; source score revisions and faculty profiles remain zero. The local backend was refreshed for the new routes.

No complete R1→2→3→4 competitive chain, deployed load certification, actual faculty photographs/appointments, actual paper/key validation or campus procedure is claimed here. M10 later-round recovery and M11 integrated/event acceptance remain. See [external round operations](EXTERNAL_ROUND_OPERATIONS.md).

## M10 recovery and organizer placeholders — 9 October 2026

- Full backend suite with `TTH_BROWSER_INTEGRATION=1`: **201 passed, 1 skipped** (opt-in local load test). The sandbox initially blocked one existing pytest temporary-directory fixture; the approved rerun passed. All four existing actual Django HTTP/PostgreSQL browser journeys remain covered.
- A supplementary focused suite including the added Round 4 faculty/panel/source recovery case and placeholder preparation: **15 passed**. Round 1 legacy/recovery plus the initial later-round recovery suite separately passed **24 checks** before that supplementary case was added.
- Full desktop/mobile Chromium suite: **100 passed**. The 32 focused results/recovery checks also passed. The initial sandbox browser process stalled during cleanup after all cases passed; approved process access produced a clean completed run.
- Frontend TypeScript/Vite build, Ruff lint, formatting of changed Python files, Django system checks and migration drift checks passed. No migration was required.
- Signed v2 checkpoints retain all saved coding revisions, private task/rubric definitions, final/no-submission bundles, workstation/supervisor evidence and reviewed judgments. Synthetic deletion/restore tests recover exact immutable records and retain source hashes; conflicts or a checkpoint missing lab judgments leave recovery material and unresolved.
- External recovery tests restore original batches, score revisions and independently reviewed question voids without duplicate marks. Round 4 coverage restores approved faculty snapshots, frozen panels/slots, original three-faculty source marks and retained roster evidence; weighted standings remain reproducible.
- Identity drift and newer unbacked records block reconciliation. Existing withdrawals survive recovery; checkpoint disqualifications are reapplied. Sessions created during review are revoked at approval. Missing historical workstation sessions become revoked tombstones with fresh identifiers; passwords/cookies are not exported or restored. Recovery refuses to interrupt another LIVE/FROZEN cohort round. Legacy signed v1 Round 1 checkpoints still reconcile.
- A private signed PostgreSQL backup was captured at `.local/m10-before-placeholders-20261009.dump` and restored into the new `tth_recovery_m10_20261009` database. The separate copy contains five rounds, zero active team sessions and one open baseline recovery incident. The source was preserved; no recovered copy was promoted.
- On the source, `seed_organizer_placeholders` created six hidden, unpublished demo faculty drafts. Repeating it created zero additional drafts. Source Round 1 remains READY and Rounds 2–5 remain DRAFT. Existing information was preserved; dates/consent/real assignments remain unset. Tests verify production refusal, real-cohort/released-round preservation and retained organizer edits. A subsequent focused **2 passed** verifies stable faculty slot identities preserve renamed drafts on repeat setup, with compatibility for the initial local audit inventory.

M10 is complete for the implemented local scope. Missing account identities, conflicting originals and records lost beyond a checkpoint still require independently reviewed retained evidence; placeholders never satisfy those checks. M11's complete competitive chain, broader outage/load acceptance and actual campus/deployment validation remain. See [recovery operations](EVIDENCE_RECOVERY.md) and [organizer inputs](templates/ORGANIZER_DATA.md).
