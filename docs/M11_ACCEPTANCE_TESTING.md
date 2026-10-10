# M11: manual Round 1–5 acceptance walkthrough

Updated 10 October 2026 for the [revised rules](RULE_UPDATES_20261010.md). This is a runnable operator checklist, not a completed test record. M11 stays **pending** until you perform the journey and record its results. Use the private `.local/ADMIN_AND_ROUND_OPERATIONS_GUIDE.md` for startup, accounts and detailed admin instructions. Keep passwords and private source evidence out of this document.

## 1. Choose the test environment and record the run

Use fictional **demo** teams/content for development acceptance. Completing this does not certify actual event content, venue/network capacity or physical rehearsal. For physical acceptance, repeat with the approved actual inputs and devices using [Round 5 rehearsal](ROUND5_REHEARSAL.md).

The [prepared professor run](PROFESSOR_DEMO.md) uses **R1 attempt 3 and R2–5 attempt 2**, all DRAFT, with both existing demo teams eligible to be considered for advancement. Use these prepared attempts without creating another one. Both teams must actually qualify through R1–3 and appear in R4's complete Green Card list to reach the two-phone final. For a later separate run, preserve released evidence and prepare new DRAFT attempts again. Do not create new predecessors midway through a published journey.

Use the latest demo DRAFT Rounds 2–5 if still unused; otherwise create new DRAFT attempts and prepare their content separately. For a new attempt, copy the required configuration/owners/policies into its editable DRAFT fields and create new attached content; do not copy IDs, clocks, state or approval/digest fields. Preserve old records. `seed_demo` is not a reset or clone command. Creating extra team identities in a cohort already released is blocked; if you need a third team to test exclusion after elimination, prepare a fresh isolated demo dataset and roster **before** any round is released.

Before starting, save a signed private database backup with a new filename:

```powershell
.venv/Scripts/python backend/manage.py backup_competition --output .local/m11-before-run-01.dump
```

PostgreSQL client tools must be on PATH. Reusing an existing output filename is refused. Read [recovery operations](EVIDENCE_RECOVERY.md) before using a separate restored database; baseline recovery incidents need review before progression.

Record these fields in a private run log or copy of the tables below:

| Field | Your value |
|---|---|
| Run ID/date, application revision and environment URL | Pending |
| Cohort, team codes and staff account names | Pending |
| R1/R2/R3/R4/R5 database IDs and attempt numbers | Pending |
| Frozen rules digests and private content references | Pending |
| Device/browser/network and accessibility observations | Pending |
| Backup/checkpoint references | Pending |
| Tester and independent verifier | Pending |

Database IDs in URLs are not round numbers. Select the recorded attempt on every desk. Use separate browser profiles for `DEMO-content`, `DEMO-verifier`, team A (`DEMO-01`) and team B (`DEMO-02`). Tabs in one profile share identity; private windows can share identity too. Use private credential files rather than copying passwords into the run log.

## 2. Entry points and draft settings

Use `http://127.0.0.1:5173` consistently for local browser work. For a deployed or LAN rehearsal, substitute its configured application URL; a phone's `127.0.0.1` points to the phone itself. Actual phone access needs a reachable host/network configuration and trusted origins, not simply the localhost development commands.

| Page | Operator task |
|---|---|
| `/admin/` | Prepare/verify missions, coding tasks, faculty, final questions and rules; mark READY |
| `/staff/roster` | Review roster/credentials before release; reviewed status changes |
| `/staff/rounds` | Open lobby, start, pause/resume, extend and end |
| `/staff/coding` | Bind the lab session and review source judgments |
| `/staff/scores` | R2/R4 original sources and R5 native-linked ledgers |
| `/staff/buzzer` | Open/close windows, confirm queue, record offline answers |
| `/staff/results` | Provisional/final review, appeals/incidents, exports and recovery |
| `/login`, then dashboard | Participant practice, information, activity and results |

Prepare content as the maker; verify it as a different account. Approve rules only after edits are complete, then mark READY as the controller. Draft edits can stale approvals. Saving information/faculty drafts is not publication; the verifier must independently publish them.

For **every round**, finish that preparation/READY sequence, then use `/staff/rounds` to **Open lobby** and **Start round** with reasons. Do not skip lobby or treat a DRAFT as playable. For Round 3, assign qualified lab sessions after READY and before play; tasks stay hidden until LIVE. For Round 4, finish the eligible team allocation before READY.

For the small demo, configure **advancement count 2 for Rounds 1–4**, no advancement count for Round 5, and `short_roster_policy: "advance_all_eligible"` where supported/needed. Preserve all other required rules and owners. These are explicitly fictional cuts; real counts remain R1→25, R2→15, R3→10 and R4→5. Do not bypass real rules with demo flags for the actual event.

| Round | Required preparation for this walkthrough |
|---|---|
| 1 | New ONLINE_HUNT demo attempt; two competitive missions, optional separate practice, six-character alphanumeric keys, owners/locations, capacity for the roster, expected mission count 2 and independent verification. See [R1](ROUND1_OPERATIONS.md). |
| 2 | EXTERNAL; `round2-wayground-v2`, eight questions for the supplied demo workbook, raw Score and exported answering-duration ties. The prepared professor draft has a 60-minute demo budget; real rules remain separately approved. See [R2/R4](EXTERNAL_ROUND_OPERATIONS.md). |
| 3 | CODING; category maxima 15/25/20/30/10, exact private lab rubrics, actual test lab Python/C versions, workstation/submission policies and independent task verification. See [R3](ROUND3_OPERATIONS.md). |
| 4 | EXTERNAL; `round4-green-card-v2`, zero points, recipient names only; three independently published synthetic faculty for one demo panel, two distinct team slots. Set panels after R3 final qualification and before rule approval/READY. Real play requires its full two-panel allocation. |
| 5 | BUZZER; 25 independently verified synthetic questions (five/stage), private answers/presentation/reveal references, exact `round5-v2` 30-mark contract, `cumulative_score_then_last_correct`, approved buzzer policies and a sufficient active budget (for example, explicitly approve 30 demo minutes rather than retaining the five-minute placeholder). See [buzzer](ROUND5_OPERATIONS.md) and [scoring](ROUND5_SCORING.md). |

Seed commands may prepare missing demo drafts, but never approve content or create qualification. Existing content is preserved. Review their prerequisites in the linked round guides rather than assuming rerunning them repairs edited settings. Replace the unverified Round 5 placeholder content with a usable synthetic pack before verification. Do not publish placeholder consent or claim actual faculty verification for a synthetic panel.

For a quick demo, you may approve a positive `appeal_minutes` of **1** before READY; this changes only the fictional rehearsal policy. Otherwise wait the configured interval. Do not alter database timestamps or frozen rules to skip appeals. You can end a demo round deliberately before its full active budget; recorded sources must reflect the work and clock evidence actually observed.

## 3. Publication gate — repeat after every round

1. End and persist the correct attempt. FROZEN is paused and does not enable ended-round score intake.
2. Complete native judging or original source review where applicable. Dry-run, pending proposals and staff previews are private; they are not public scores.
3. In Results, inspect entries, maxima, eligibility, clock/evidence gaps, incidents, pending batches and cutoff ties. Resolve/reject stale or invalid proposals through the reviewed workflow.
4. Maker proposes **PROVISIONAL** with a reason. The different verifier/publisher inspects and approves. Confirm the team sees the published snapshot and appeal deadline.
5. Wait the full appeal interval and resolve material issues. Changed scoring/ranked metrics need a revised provisional snapshot and a new appeal interval. Resolve cutoff ties using the frozen supported policy and actual retained evidence.
6. Maker submits a fresh **FINAL** proposal; different authorized verifier/publisher approves. Record snapshot ID, revision, qualifier codes (R1–4) or winner codes (R5), entries and evidence references.
7. Download the private signed ended/final checkpoint. Confirm next-round eligibility comes from the latest FINAL snapshot. A provisional result, Green Card image or staff preview alone grants no next-round participation.

Before finalizing each predecessor, try to open/start the next round as staff and access its competitive activity as a team. **Expected:** progression remains blocked; public information may still be readable. After final approval, **expected:** only active latest-attempt qualifiers gain the next activity gate. Real eligibility still requires the next round's state and, for coding, assigned session.

## 4. Round 1 — missions, receipts and first qualification

1. As maker, configure two new synthetic missions with known six-character codes, for example `AB1024` and `CD0042`; independently verify both and approve rules. Set the mission count to 2, then mark READY.
2. Team signs in, opens practice and verifies a correct practice answer changes no competitive score. Publish the rehearsal information separately if it is meant to be visible.
3. Controller opens the lobby, then starts Round 1. Record the common clock and control version.
4. Team A explicitly opens and correctly solves both competitive missions. Team B explicitly opens and solves only the first. Test QR/mission-link access and fallback-code access; preserve the leading zeros in `CD0042`.
5. Save the accepted receipt(s). Reload a solved mission and verify score stays unchanged. An uncertain response must recover the original request/receipt; do not substitute a new action UUID.
6. Pause, verify new scored activity is blocked and the active clock is frozen; resume and confirm frozen time is excluded. End and confirm late/new answers cannot score.
7. Run the publication gate. **Expected:** A=2/2, B=1/2; both qualify under the configured demo cut 2. Provisional alone did not unlock Round 2. Record final R1 entries and qualifiers.

Put wrong-answer cooldown/quota escalation, alternate answers/voids and irreversible paper fallback in **separate** branches/attempts using [R1 operations](ROUND1_OPERATIONS.md). Those checks can change the baseline scores or permanently disable online play; do not activate paper fallback midway through this baseline journey.

## 5. Round 2 — Wayground export

1. Confirm the R1 final gate: before final publication R2 eligibility is held; afterward both qualifying demo teams can enter. Confirm keywords are visible in LOBBY and hidden after LIVE.
2. Run the quiz externally, then END the website attempt. Select it in Scores and upload the supplied original Excel workbook from the private manifest. **Expected:** three players; scores 7000/5390/3180, durations 24/25/33 seconds, eight questions. Keep the original file unchanged.
3. Map the first player to DEMO-01 (A), second to DEMO-02 (B), and explicitly exclude the third with a demo reason. Do not invent a third qualifying team. Verify each mapping against the original before dry-run. **Expected:** A=7000, B=5390, no Accuracy/Correct conversion or hand-in timestamp.
4. Check negative branches: an unmapped player, duplicate team or exclusion without a reason blocks dry-run. A maker cannot independently commit their own batch. Repeating the acknowledged upload preserves the same checksum/report evidence.
5. A different verifier checks the original download and calculated preview, then commits. Publish PROVISIONAL independently, verify team-visible raw points/answering durations, resolve appeals and publish FINAL independently after the window. **Expected:** A ranks above B; both qualify under demo cut two; only final publication releases R3. Test equal raw scores with lower answering duration in an isolated fixture rather than changing the supplied original report.


## 6. Round 3 — lab binding, durable saves, locked work and judging

1. After R2 FINAL, open each team's coding workspace in its intended lab browser. In `/staff/coding`, bind each active qualified session to a distinct physical workstation with evidence. An unassigned second browser should not obtain writable tasks.
2. Start the round. For the baseline, A saves correct responses to every task; B saves a clearly wrong response to at least one task and earns zero under the fixed rubric. Execute/evaluate using the approved lab tools; the website does not run source code.
3. Confirm every save acknowledgment and revision. Reload to verify confirmed source survives. Test a stale second-tab write against an older revision: it must not overwrite newer confirmed work. Preserve unknown-save requests for **Retry same save**.
4. A explicitly final-submits; record the confirmation digest/time and verify later edits cannot change locked work. Leave B's confirmed wrong work unsubmitted, then end the round to exercise cutoff finalization. **Expected:** B's last acknowledged work is frozen at cutoff, unsaved edits excluded.
5. On `/staff/coding`, maker inspects exact frozen source/rubric, records lab verdicts for every saved bundle and retained supervisor/time references, then proposes judgments. Different verifier approves. No saved/credited task or completion time may be invented during judging.
6. Run the publication gate. **Expected:** A=100/100, B=0/100; both qualify under cut 2. Public results include aggregate marks/correct-task count/final time, not private source or hidden tests. Record final R3 entries.

## 7. Round 4 — professor Green Cards

1. Keep actual/published faculty and optional assignment information separate from card decisions. The demo's synthetic faculty and panel can still be shown, with missing portraits using initials. Prepare new `round4-green-card-v2` rules, independently approve and mark READY.
2. Start the round and record the synthetic professor's card decisions. For both teams to reach the final, the demo list contains both DEMO-01 and DEMO-02. Preserve that complete source list.
3. End. In `/staff/scores`, enter only those team names/codes, confirm the complete-list checkbox and dry-run. Missing list confirmation, unknown/ambiguous/duplicate or unqualified names must not commit.
4. Different verifier checks the originals and commits. Expected: both have Green Cards, no numerical score/ranking and zero carried points. Unlisted entrants must not receive cards automatically. A corrected complete list replaces effective decisions while retaining prior records.
5. Run the publication gate. Only eligible listed recipients get FINAL qualification; do not fill remaining slots from unlisted teams. Provisional or a displayed card alone does not authorize a buzz. Record final R4 entries and qualifiers.

## 8. Round 5 — 25 offline questions, native buzzes and one winner

1. Confirm all four prior final snapshots are present, reviewed and free of material blockers. Carried totals are final R1+R2+R3 points; R4 contributes zero. Use the actual R2 export metric. With supplied R2 scores 7000/5390, R1 2/1 and R3 100/0, expected carried totals are A=7102/B=5391. Recalculate if your reviewed R3 verdicts differ. Keep both phones signed in as their respective qualified teams.
2. Controller opens the lobby/starts, selects the correct frozen question in `/staff/buzzer`, supplies a reason and opens a fresh window. Present its matching synthetic content offline. Use [the host run sheet](ROUND5_REHEARSAL.md) for all five stages.
3. Both teams press close together. Controller closes the window and confirms the persisted queue **before** calling a team. Expected order follows precise database admission times; no client-clock/network-latency compensation. Do not assume A physically tapped first or force its priority.
4. For one selected question, have the actual first buzzing team answer wrong, then call the next buzzing team for a correct answer. Record each native host verdict immediately with exact press/answer/reference; observe that an unbuzzed team cannot take the answering opportunity. If the chosen order makes B the correct team, this can be the baseline's one B-credit question.
5. Complete **all 25 questions**, five/stage. For the predictable baseline, arrange 24 correct answers credited to A and one to B, with no voids. If observed outcomes differ, retain them and recalculate the expected totals instead of editing evidence to fit the example. Stage 4 expands offline; reveal steps do not change its one mark. Stage 5 is word decoding and awards two per correct answer.
6. Exercise double tap, unknown response/reload receipt recovery, pause and a fresh window. Expected: one effective team position, original UUID/window recovery, old requests do not migrate into another question, and no acceptance while paused/closed. If a retry creates an extra played window, every window needs reviewed coverage and older duplicate question windows need reviewed voiding to prevent double credit; keep this out of the no-void baseline or record the changed expected maximum.
7. End. On `/staff/scores`, select R5 and **Load native host records as source drafts**. Complete every finalist/window row with explicit CORRECT/WRONG/NO_ANSWER/NO_BUZZ/NOT_CALLED or reviewed global VOID, native IDs, answer, reveal step and private references. Do not paste aggregate points or client timestamps.
8. Dry-run, check 25-question/every-window coverage and original completion/priority evidence; different verifier commits. If B gets the first stage-1 question and A the other 24, expected R5 credit is A=29/B=1, maximum 30. Add actual R1–3 carried totals; stage maxima are 5/5/5/5/10. An encoding question credited to B instead is worth two, so recalculate from actual evidence.
9. Run the publication gate. Provisional shows totals without an award. After appeals and independent FINAL approval, **expected:** only A is **The Winner of Tech Treasure Hunt**, exactly one `winner_codes` entry, empty `qualifier_codes` and no Round 6. Record final snapshot and signed v3 checkpoint.
10. Separately exercise equal cumulative scores with different original last-correct host completion times: earlier completion wins. Exact/missing-time ties remain held for the frozen adjudication policy; press/import/review time cannot replace completion time. Use a separate prepared branch/attempt; ordinary imports cannot replace this finalized award.

## 9. Interruptions, recovery, access and device checks

Record each check separately with its observed result; the happy journey alone does not finish M11.

| Check | Expected behavior and evidence |
|---|---|
| Wrong role/self-review | Team denied staff pages/private exports; maker cannot verify own content, commit own source, approve own judgment/result/recovery |
| Lost write response | Original UUID/payload recovered after reload; no duplicate points, publications or press credit |
| Pause/expiry/late request | Active time excludes pauses; controls persist ended/cutoff state; late/closed activity cannot score |
| Application restart | Acknowledged evidence survives; inspect persisted state before continuing. Restart alone does not close a valid LIVE buzzer window; deliberately pause/close interrupted presentation |
| Database/service interruption | Unavailable status shown; no guessed accepted writes/timestamps; preserve pending requests and material coverage gaps |
| Qualification/status changes | Latest FINAL gates respected. Reviewed withdrawal/disqualification revokes access and post-final impact stays under review without automatic promotion. Perform after baseline or in an isolated branch |
| Signed recovery | On a new isolated recovery database, stop cohort play, recover R1–4 dependencies and reconcile R5 v3 independently; reproduce original credit/winner with revoked sessions and closed windows. Resolve baseline incidents separately |
| Conflicting/missing recovery evidence | Changed original completion, missing/newer carried finals or uncovered outage interval keeps recovery material and blocked; preserve copies, never backdate |
| Real device/accessibility | Readable phone layouts, large buzzer, keyboard/focus support, camera/fallback, accurate acknowledgment and no inaccessible content; record actual devices/network |
| Concurrent/load capacity | Record tested team/browser count, simultaneous presses, errors, queue correctness, server/database observations and agreed acceptable response times; no production-capacity claim from a two-phone test |

Use [R1 paper/correction branches](ROUND1_OPERATIONS.md), [coding judgment/cutoff checks](ROUND3_OPERATIONS.md), [external void/correction checks](EXTERNAL_ROUND_OPERATIONS.md), [native recovery](EVIDENCE_RECOVERY.md) and [physical rehearsal record](templates/ROUND5_REHEARSAL_RECORD.md). Do not delete evidence, change clocks/state via SQL or manufacture final predecessor snapshots to bypass the journey.

## 10. Sign-off record

| Checkpoint | Observed outcome/snapshot IDs and private references | Pass/fail/blocked | Tester/time | Independent reviewer/time |
|---|---|---|---|---|
| Environment/roster/draft release | Pending | Pending | Pending | Pending |
| R1 → R2 gate | Pending | Pending | Pending | Pending |
| R2 → R3 gate | Pending | Pending | Pending | Pending |
| R3 → R4 gate | Pending | Pending | Pending | Pending |
| R4 → R5 gate | Pending | Pending | Pending | Pending |
| R5 carried totals/one winner | Pending | Pending | Pending | Pending |
| Permission/retry/negative branches | Pending | Pending | Pending | Pending |
| Restart/outage/signed recovery | Pending | Pending | Pending | Pending |
| Load/devices/accessibility | Pending | Pending | Pending | Pending |

For failures, record the triggering action, expected versus observed behavior, exact attempt/version, timestamp and retained evidence/incident reference. Fix and rerun the affected check plus its dependent progression. Do not label unperformed checks PASS. Overall M11 status: **PENDING**. Physical rehearsal/production release: **PENDING** until their separate evidence and approvals exist. Update [development status](DEVELOPMENT_STATUS.md) and [test evidence](TEST_EVIDENCE.md) only after the recorded acceptance is reviewed.
