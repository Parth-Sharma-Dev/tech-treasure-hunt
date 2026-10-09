# Local acceptance evidence

Recorded 7 October 2026. Scope: implemented Round 1 behavior using synthetic fixtures. Later-round competition, production hosting, real mission routes, actual rosters and physical device/paper drills are not certified here.

M7 participant portal validation was added on 8 October; the original Round 1 evidence below is retained as a dated record.

Round 5 M12/M13 implementation and supplied scoring rules were recorded on 9 October. The sections below cover local buzzer and winner validation; signed native recovery remains M14. Earlier results retain their dated scope. See [Round 5 scoring](ROUND5_SCORING.md) and [updated milestones](DEVELOPMENT_STATUS.md).

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

## M12 website buzzer and finalist portal — 9 October 2026

- Full PostgreSQL backend suite with `TTH_BROWSER_INTEGRATION=1`: **213 passed, 1 skipped** (opt-in load test). The focused content/portal/rules suite passed 28 checks; native buzzer/round-clock checks passed 27. Initial existing temporary-directory access restrictions were resolved with approved execution.
- Full desktop/mobile Chromium suite: **112 passed**. The focused buzzer/portal/external suite passed 34 checks. The first mocked participant cases omitted a required clock fixture; the corrected fixture and final suites passed.
- TypeScript/Vite build, Ruff lint/format checks, Django system checks, migration drift check and Node syntax checks passed.
- A fifth actual Django HTTP/PostgreSQL browser journey covers staff login/start, frozen question opening, team login, native press with deliberate response loss, reload/exact-receipt recovery, confirmed closure and a second question window. All data uses the isolated test database; it does not create application qualification or scores.
- A threaded database test holds an earlier press before its team lock, lets a later same-team press commit first and starts admin closure. Closure waits for the earlier transaction, then retains its earlier database time and one effective team position. This tests reversed commit order and draining, not production capacity.
- Readiness tests cover all five stages, independent verification, frozen private content and partial-update verification invalidation. Endpoint tests cover duplicate UUID replay, repeated taps, private-key redaction, unqualified teams, forged client time, foreign receipt IDs, CSRF/participant staff denial, qualification-impact incidents, pause/resume window isolation and exact timestamp ties held for review.
- Frontend checks cover the single-request buzzer with prefetched CSRF, six-digit timestamp display, disabled/ineligible/paused states, lost-response recovery across reload, same-UUID/window retry, admin confirmed order/ties, Round 4 dashboard progression and mobile overflow.
- Signed private backup `.local/m12-before-migration-20261009.dump` preceded migration 0014. Source Round 1 remains READY; Rounds 2–5 remain DRAFT. `seed_buzzer_demo` prepared five unverified Round 5 placeholders and an unpublished information draft; repeat setup preserved them. Source native press count remains zero and no Round 4 qualification was fabricated.

M12 is complete locally. Actual question packs/images/encoding/reveals, host rules, schedule and real Round 4 qualifiers must still be independently supplied/reviewed before live play. M13 scoring/winners, M14 signed buzzer reconciliation, broader M11 load/outage/full-chain acceptance and actual phone/network/event rehearsal remain. See [operating instructions](ROUND5_OPERATIONS.md).

## M13 cumulative final scoring and one event winner — 9 October 2026

- Final clean, serial backend run with `TTH_BROWSER_INTEGRATION=1`: **230 passed, 1 skipped** (opt-in load test). A supplemental runner initially collided with the full suite's shared test database; the competing setup and two legacy browser requests failed. The non-overlapping rerun passed all journeys. The application database was not used by those fixtures.
- Full desktop/mobile Chromium: **122 passed**; the focused host/buzzer/results/external group passed 68 checks. TypeScript/Vite build, Ruff lint/format, Django system/migration drift checks and Node script syntax checks passed.
- The organizer supplied five questions per stage, two marks/correct, zero wrong/unanswered penalties, buzzer-only passing, carry-over, earlier last-solved completion and one winner. The implementation uses summed latest final Round 1–4 scores and original host-server completion of the last credited correct Round 5 answer; it never substitutes buzzer time or import/review time.
- Native tests cover exact 25-question/50-mark rules, response priority, host UUID replay and timestamp forgery rejection; atomic independent ledger commits, exact press/answer references, explicit per-finalist rows, corrected verdicts retaining original time, stage totals, missing question coverage, carried scores outweighing Round 5 credit, completion tie ranking and missing-time ties held for review.
- Further tests cover staff/CSRF guards, imported-points rejection, stale carry-over, pending batches, renewed provisional appeals, retained equal-time adjudication across draft rows and rejection of Round 5 through the legacy unlinked score service.
- A sixth actual Django HTTP/PostgreSQL browser journey prepares the first 24 questions in an isolated fixture, then exercises the last live buzz/host answer, end, CSV dry run, independent source commit, provisional publication, final review and one event winner. Only the fixture advances its publication clock after provisional results. The first script assertion saw an older 'Published' marker before the final acknowledgment; waiting for the actual final response fixed the test race.
- Final snapshots carry one `winner_codes` entry, an event title and empty `qualifier_codes`; no Round 6 is created. Public entries contain aggregate stage/carried totals and completion time, not raw answers, receipts or source references. Historical/under-review awards retain their evidence without automatically promoting another team.
- Signed private backup `.local/m13-before-migration-20261009.dump` preceded migration 0015. The source Round 5 draft now has 25 unverified slots (five per stage) and the supplied scoring contract. Repeated preparation adds zero records and preserves existing content. Source R1 remains READY; R2–R5 remain DRAFT; native answer/score-ledger/final-award counts remain zero. No prior scores or qualifiers were fabricated. The local backend was refreshed for the new routes.

M13 is complete locally. Actual packs/images, approved host/rules references, final prior-round results and event procedures still require release review. M14 signed native recovery and M11 complete-chain/load/outage/device acceptance remain. See [scoring operation](ROUND5_SCORING.md).

## M14 signed native recovery and rehearsal procedures — 9 October 2026

- Full serial PostgreSQL backend suite with `TTH_BROWSER_INTEGRATION=1`: **243 passed, 1 skipped** (opt-in load test). All six existing actual Django HTTP/PostgreSQL browser journeys passed. No competing pytest runner used the shared test database during this run.
- Full desktop/mobile Chromium suite: **124 passed**. Focused results/recovery checks passed **34**. TypeScript/Vite build, Ruff lint/format (80 Python files), Django system/migration drift checks and local documentation link checks passed. No migration was required.
- Focused Round 5 recovery scenarios passed **13** across two serial runs (nine core/dependency cases, then four award/permission/export cases). The earlier combined legacy/native recovery suite passed **33**. Initial tests exposed a cloned immutable fixture and over-broad legacy short-roster configuration enforcement; the fixture now appends properly and native configuration validation applies to Round 5 without preventing earlier source reconciliation.
- Signed v3 Round 5 checkpoints inventory frozen private questions/reveal references, every native window/closure/press, original received/admitted/completion times, host priority/verdict sources, original score batches, superseding question ledgers and winner snapshots. Bounded authenticated JSON/CSV exports retain signed manifests, cursor invalidation and no-store responses; participants cannot download them. Cookies and passwords are absent.
- An isolated synthetic drill plays/reviews all 25 questions and publishes one final award, then removes native questions/windows/closures/presses/answers/batches/ledgers/publication records and historical sessions from the test database. Independent recovery reproduces exact immutable native records, cumulative entries, original last-correct completion and the original single winner, with empty next-round qualifiers, 25 ledgers, closed windows and revoked session tombstones with fresh unusable identifiers. The older restored round starts ENDED and returns to its retained FINALIZED state. Replayed review does not duplicate recovery or credit.
- Signed carried-result provenance binds original latest attempts, approved rules/state, exact final snapshots and material scoring/qualification evidence. Newer same-score snapshots, missing finals, different attempts and review-time rule changes block recovery. Earlier recovery's control-version increment and resolved recovery bookkeeping do not substitute a new carried basis or prevent legitimate dependency-first recovery. Open material recovery incidents still block carry-over until separately resolved.
- Original completion conflicts, inconsistent published credit/winners and missing coverage retain material incidents. Withdrawal survives while historical award evidence remains intact. Restoring FINAL evidence from an ENDED copy requires publication permission in addition to independent verification. Private exports invalidate cursors if carried evidence changes.
- Host/controller/scorekeeper procedures now cover all five stages/reveals, queue closure, offline passing, original host confirmation, review/appeals, duplicate/lost responses, restart/pause and isolated recovery. Actual staff assignments, device/network evidence and physical rehearsal remain labeled **PENDING** in the new record template; no real rehearsal is certified.
- The source database was preserved: Round 1 remains READY; Rounds 2–5 remain DRAFT; 25 Round 5 questions remain unverified; press/host-answer/ledger/final-award counts remain zero. The local backend was refreshed for the recovery extension. No source results, eligibility, real content or rehearsal evidence were fabricated.

M14 is complete locally. M11's full competitive chain, broader outages/load/accessibility acceptance and actual campus/phone/physical rehearsal remain. See [recovery operations](EVIDENCE_RECOVERY.md), [rehearsal run sheet](ROUND5_REHEARSAL.md) and [milestone status](DEVELOPMENT_STATUS.md).
