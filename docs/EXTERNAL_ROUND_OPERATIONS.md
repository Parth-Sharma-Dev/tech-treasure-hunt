# Round 2 Wayground and Round 4 Green Card operations

Updated 10 October 2026. [Current rules](RULE_UPDATES_20261010.md) supersede earlier manual quiz/faculty-mark assumptions for new attempts. Historical schemas and evidence remain supported.

## Round 2 — actual Wayground report pending

The organizer will supply the exported Excel workbook. Exact worksheet/column mapping, numerical metric, maximum, team matching and any genuine timing evidence require that file. It has not arrived yet; the old correct-question-ID CSV is legacy support, not the promised new Wayground format. Do not infer quiz marks from game points/accuracy interchangeably, fabricate finish times or claim an Excel import passed. The fresh R2 draft remains on the legacy schema until the report is inspected and the replacement format implemented/reviewed.

## Round 4 — names only, no numerical marks

Before READY, configure `ranking_policy = green_card_qualification` and `score_schema = {"version":"round4-green-card-v2","max_score":"0","qualification_only":true,"carry_over_points":0}`. Real advancement is capped at five, demo at the configured count. Approved faculty information and optional interview allocations remain separate from scoring; the new intake does not require criterion marks or faculty IDs.

After ENDED, select the exact attempt on `/staff/scores`. Enter a private intake reason and Green Card recipient **team names/codes, one per line**. Confirm the list is complete; every unlisted prior finalist is recorded as no card. Dry-run checks unknown/ambiguous/duplicate/inactive/unqualified names and too many recipients. A different verifier reviews the complete original list and commits it. Corrections append replacement card evidence for all entrants rather than adding credit.

Publish PROVISIONAL, finish appeals/material review, then independently publish FINAL. The final qualifiers are exactly the eligible card recipients, with no automatic filling of unused slots. Public results show received/not received and final qualification, without scores or rankings. All carried R4 points are zero. Signed exports/recovery include `greencardrevision` and original import batches.

Use `/staff/roster` for independently reviewed roster/status changes and credentials. Identities remain frozen after cohort release; withdrawal/disqualification revoke access and open dependent qualification-impact review where required. See [recovery](EVIDENCE_RECOVERY.md) and [M11 walkthrough](M11_ACCEPTANCE_TESTING.md).

## Historical schemas — reference only

<details><summary>Earlier Round 2 manual quiz and Round 4 weighted faculty operation</summary>

# Round 2 and Round 4 operations

M9 supports paper-quiz/faculty scores and roster administration. M12/M13 add [Round 5 buzzer and reviewed final scoring](ROUND5_SCORING.md). `/staff/scores` supports its separate native-evidence-linked `round5-v1` ledger; the legacy unlinked external service remains Round 2/4 only. Signed native recovery remains M14.

Use `/staff/scores` for source scores, `/staff/results` for provisional/final publication and appeals, `/staff/roster` for teams, and Django admin **Faculty profiles** for the approved directory. Staff workflow links appear on each desk. Sign in with an authorized staff account; participant accounts cannot use these endpoints.

## Configure and release

Configure the round in DRAFT, verify the current rules, then mark READY. Frozen rules include the schema, advancement count and Round 4 panel/slot assignments. Rule approval becomes stale when approved faculty information changes before READY. Round 2/3/4 cannot open a lobby until the previous round has an independently published final qualifying list. Round 4 also needs a frozen slot for each eligible team.

`seed_external_demo --actor DEMO-content` prepares only missing unsigned schemas for existing demo DRAFT rounds. It preserves already configured/released attempts, does not change Round 1, create faculty, score sheets or qualification, and never approves rules. Small demos retain their explicit demo advancement count. Real Round 2/4 settings must use the manual counts below.

Keep the other required owner, appeal, retention, tool, movement, delivery and evidence-reference policies. Configure actual information/schedules/venue through independently published Round information records. All authoritative timestamps use UTC; the portal displays IST.

## Round 2 paper quiz

The supplied manual specifies 12 October, 1:45–2:30 PM, 25 Round 1 qualifiers, 30 paper questions and 15 qualifiers. Blocks: AI 6, Python 7, C 7, logic/puzzles 6, clue links 4. Correct answers earn one mark; incorrect/unanswered answers earn zero. No negative marking. Rank by total, then earlier volunteer-recorded hand-in time, then a sealed common reserve question for tied teams.

Set delivery EXTERNAL, active budget `2700000`, advancement count `15`, ranking policy `score_then_finish_time`, and qualification tie policy `supervised_reserve_question`. A smaller rehearsal must be marked demo. Freeze canonical question IDs shared across paper sets A/B, whose displayed question orders differ. Example schema, replacing IDs if the paper uses different canonical IDs:

```json
{"version":"round2-v1","max_score":"30","question_ids":["Q01","Q02","Q03","Q04","Q05","Q06","Q07","Q08","Q09","Q10","Q11","Q12","Q13","Q14","Q15","Q16","Q17","Q18","Q19","Q20","Q21","Q22","Q23","Q24","Q25","Q26","Q27","Q28","Q29","Q30"]}
```

R2 CSV columns must appear exactly in this order:

```csv
team_code,correct_question_ids,official_finish_active_ms,source_reference
SYNTHETIC-A,Q01|Q02|Q03,1800000,private-paper-sheet-a
SYNTHETIC-B,,2100000,private-paper-sheet-b-zero-credit
```

Enter the question IDs awarded credit, separated by `|`, or an empty cell for explicit zero credit. Do not import an untraceable aggregate total. Map each answer sheet to canonical question IDs using the approved paper/key. Keep the actual questions, answers and paper/key in authorized organizer custody.

`official_finish_active_ms` is integer active milliseconds from the official start, excluding recorded pauses; it must fit the operational budget. Reconcile any absolute volunteer hand-in timestamp against recorded clock intervals and retain that timing evidence with the source reference. The website cannot attest that a paper sheet or handwritten time is truthful; the independent reviewer checks the originals.

Round 1 keywords appear on the Round 2 page during READY/LOBBY and disappear there once play starts. Teams must record them before entering the supervised phone-free hall. Linked questions must remain solvable without keywords. Lab/hall supervision enforces the physical phone rule.

If a question is faulty after play, use **Propose a faulty question void for every team**. Provide its released ID, reason and private evidence. A different verifier approves or rejects it. An approved void removes that question from everyone's effective score and reduces the maximum, preserving original sheets and marks. At least one question must remain. Republish provisional results and restart appeals after any scoring change. Questions cannot be silently removed from frozen rules.

## Round 4 faculty interview

The supplied manual specifies 13 October, 1:15–2:15 PM, ten Round 3 qualifiers, two panels of three faculty, five teams per panel, and ten-minute slots (eight-minute interview plus scoring/changeover). Answers may be in English/Hindi. Use a common equally difficult private question pool.

Create designated contest faculty profiles in admin. Record display name, role, public location/contact channel, an approved HTTPS portrait URL if supplied, and a private consent reference. Missing portraits use accessible initials placeholders. A different verifier selects **Independently approve faculty consent and publish profile**. Later draft edits preserve the last approved release. Consent references and draft details remain private. Host portraits at an approved stable HTTPS location; this milestone uses URLs rather than a photo-upload service. Withdrawing a published profile requires an independently approved `visible=false` revision.

Set EXTERNAL, budget `3600000`, advancement count `5`, ranking policy `weighted_faculty_criteria`, qualification tie policy `supervised_reserve_question`, and:

```json
{"version":"round4-v1","max_score":"100","rounding":"half_up_3"}
```

Configure `faculty_panels` in the round's rules using faculty IDs from the admin list. Each panel has a unique label, three distinct approved faculty IDs and ordered, nonoverlapping timezone-aware slots. Each active assigned team appears once. Real Round 4 requires two panels and ten teams. Example structure (synthetic IDs, not actual appointments):

```json
[{"label":"Panel A","faculty_ids":[101,102,103],"slots":[{"team_code":"SYNTHETIC-A","start":"2026-10-13T13:15:00+05:30","end":"2026-10-13T13:25:00+05:30"}]}]
```

Fill all ten real slots before release. After READY, changing panel composition/team allocation requires a new approved attempt; silent faculty substitutions are unsupported. Eligibility and the current-attempt rule determine whose own assignment is visible. Approved faculty directory entries remain available as public event information within the team's cohort.

R4 CSV columns:

```csv
team_code,faculty_id,technical,problem_solving,communication,coordination,source_reference
SYNTHETIC-A,101,8,7,6,5,private-faculty-sheet-101
SYNTHETIC-A,102,8,7,6,5,private-faculty-sheet-102
SYNTHETIC-A,103,8,7,6,5,private-faculty-sheet-103
```

Every criterion is 0–10, finite, with at most three decimal places. All three assigned faculty rows are required for each imported team; missing marks are never inferred. Original per-faculty marks/references remain immutable private source evidence. The precision policy computes `technical × 4 + problem_solving × 2.5 + communication × 2 + coordination × 1.5` from exact panel sums divided by three, then rounds the total half-up to three decimals. Displayed averages are rounded separately to three decimals; tie comparison uses exact criterion sums, so display rounding cannot invent a tie. Independently verify this precision policy with organizers before real release.

Rank by total, then technical average, then problem-solving average. A remaining qualification-boundary tie requires one common reserve question, complete tied-team order and private evidence reviewed during final publication. Public results show reviewed totals and criterion averages, not individual faculty score sheets. Final top-five qualifiers receive Green Cards; M12 uses the latest reviewed final qualification to gate the Round 5 buzzer. Published results link back to the dashboard; the displayed card alone never authorizes a press.

## Intake, corrections and publication

1. End and persist the round clock using Round controls. FROZEN is paused, not ended. Source intake opens only in ENDED/PROVISIONAL.
2. A controller/adjudicator enters a reason and uploads/pastes UTF-8 CSV (at most 1 MB) or fills manual source rows. Both use the same validation. **Dry-run** creates a private batch, never score revisions or public results.
3. Check its errors, original rows and calculated preview. Unknown/ineligible teams, duplicates, schema/header errors, out-of-range values, invalid timing and incomplete/wrong faculty assignments block the entire batch. Fix errors in a new batch; reject invalid/stale pending batches so they cannot block finalization.
4. A different authorized verifier checks original sheet/key/timing/panel evidence, confirms review, supplies a reason and commits the entire batch atomically. Replayed action UUIDs return the recorded result; committed batches never award duplicate summed marks.
5. Corrections use a new source batch with an explicit correction reason. Its committed revisions supersede each affected team's previous revision without changing original evidence. After stale intake, prepare a fresh reason/batch against the latest state. Rejected batches are retained. Once FINALIZED, ordinary score edits/imports/voids are blocked; post-final correction requires separate adjudication rather than changing history.
6. In Results review, select the round and propose PROVISIONAL from the current evidence. A different publisher/verifier approves. Participants see only approved snapshots. Resolve material appeals/incidents and pending source/void proposals, then wait for the complete appeal window.
7. Any change to scores, voids, status or ranked metrics requires a revised provisional publication and a new full appeal window. Finalize through a fresh, independently reviewed FINAL proposal. Cutoff ties need the complete reserve-question decision; team-code display order is never a competitive tie-break.

Final R2 qualifiers become eligible for R3; final R3 qualifiers become eligible for R4. New attempts and unresolved qualification-impact/recovery incidents can suspend access. Historical results stay readable. A material incident or version/evidence change prevents stale proposals from publishing.

## Real roster administration

Use Team roster. Choose real/demo explicitly, enter one application or paste CSV with exact columns:

```csv
code,name,leader_name,member_count,roster_reference,status
SYNTHETIC-A,Synthetic team,Synthetic leader,3,private-application-a,ACTIVE
```

Codes use uppercase letters/digits/underscore/hyphen (24 characters maximum). Teams require 3–4 members. New teams require unused account names; existing accounts are never repurposed. A different verifier reviews the complete proposal. New participant users have unusable passwords until a controller issues credentials through **Issue credentials for TEAM** using a reason and a validated password. Passwords are not stored in pending browser storage or audit payloads; the database stores Django's password hash. Give credentials through the event's approved channel.

Create/edit roster identities before any round in that cohort is released. Afterwards, use reviewed withdrawal/disqualification; identity edits and automatic reactivation are blocked. Approved changes increment access versions and revoke affected sessions. Credential reissue also revokes old access and uses an expected version. A post-final status change opens material qualification-impact incidents, preserving published history until reviewed. It does not silently promote another team or replace final snapshots.

Unknown write outcomes on score/roster desks retain their UUID/body across reload; retry the saved action. Credential retries retain their request only in the current page's memory so plaintext passwords never enter session storage. After navigation/reload, refresh access state before a deliberate new credential action.

## Local acceptance and remaining inputs

Synthetic tests cover source validation, atomic/idempotent commit, independence, revisions, global voids, reserve ties, qualification, consent/draft redaction, faculty averaging, roster review and session invalidation. An isolated actual Django/PostgreSQL browser journey exercises score intake, independent commit/publication, participant results, roster creation/review and credentials. See [test evidence](TEST_EVIDENCE.md).

Actual paper/key, applications, faculty details, panel slots, venues and private content remain organizer inputs. M10 recovery covers Rounds 1–4; M12/M13 buzzer and final scoring are complete locally. M14 adds signed native recovery and M11 covers the complete event journey/load/outage rehearsal. See [milestone status](DEVELOPMENT_STATUS.md). No production deployment or physical-event verification is implied.

</details>
