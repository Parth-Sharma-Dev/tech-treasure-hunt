# Round 5 — offline answers with a website buzzer

Requirements recorded 9 October 2026, updated through M14. Information/buzzer are implemented in M12; reviewed cumulative scores and one winner in M13; signed native recovery and rehearsal procedures in M14. See [buzzer operation](ROUND5_OPERATIONS.md), [scoring operation](ROUND5_SCORING.md) and [rehearsal](ROUND5_REHEARSAL.md). Actual event inputs remain pending.

## Confirmed format

Round 5 has **five stages within the final round**. The host presents images, keywords and encoded words at the venue; teams answer offline. Eligible participating teams press a buzzer on the website's Round 5 page. The admin sees the server-recorded press times, and the team with the earliest valid server-recorded press gets the first opportunity to answer offline. The website also provides approved information, eligibility, reviewed results and winners. Answers are not submitted through the website.

| Stage | Activity | Marks/question | Stage total |
|---|---|---|---|
| 1 | AI image recognition | 1 | 5 |
| 2 | Answer from keywords | 1 | 5 |
| 3 | Image abnormalities | 1 | 5 |
| 4 | Progressive image guessing | 1 | 5 |
| 5 | Word encoding/decoding | 2 | 10 |

Five questions/stage, 25 total, 30 marks. Wrong/unanswered remain zero, with no negative marks. R4 Green Cards qualify teams without carried points; final R1–3 points carry into the event award. Stage/overall duration still requires actual organizer input. See [current rules](RULE_UPDATES_20261010.md).

## Entry and public information — implemented locally in M12

Use the latest independently finalized Round 4 qualifier snapshot in the same cohort as the source of Round 5 eligibility. The existing Round 4 plan awards five Green Cards; the expected finalist count follows that plan and still needs organizer confirmation. A visible Green Card alone must not bypass backend eligibility or unresolved qualification-impact/recovery incidents.

The Round 5 page should show its offline-answer/website-buzzer format, all five stage descriptions, approved schedule/venue, host/help contacts, qualification reason, buzzer availability and published results after play. Nonqualifying teams may read approved public information and same-cohort published results but cannot buzz. Only approved finalists may participate at the venue. Private images, unrevealed crops, encoded questions, expected abnormalities and answer keys stay out of participant API responses and public assets.

The dashboard now links to Round 5 and its direct same-cohort overview is available. The five stage descriptions are public; actual schedule/contact drafts still require independent publication. BUZZER attempts offer the participant button, with backend qualification/window checks. Unqualified teams cannot create buzzes.

## Website buzzer and admin ordering — implemented locally in M12

The organizer's selected policy is **first valid press received by the server**, without adjustment for participant network latency or phone performance. Participants are responsible for using a responsive smartphone and maintaining connectivity on the available event network. Do not backdate a buzz using client clocks, browser click times, estimated round trips or participant-reported delays.

- Show a large, accessible buzzer on the Round 5 page for authenticated, eligible finalists. The backend checks cohort, latest attempt, team status, Round 4 qualification, LIVE state and the current open question window on every request.
- The admin opens/closes the buzzer for the current stage/question and starts a new versioned window for the next question or an approved retry. Pause/end closes acceptance. Keep previous windows and press records; resetting never erases history.
- Record server UTC time using PostgreSQL at successful buzzer admission, after authentication/window admission and before contended team locks. All application instances use that database clock. Retain the later admitted/persisted timestamp separately. Client fields cannot determine order; receipt time rather than response/commit/lock-acquisition order determines priority.
- Keep durable press identity, team, round/attempt, stage/question, window version and server timestamp. Retries use the original request identity and recover the recorded acknowledgment without another competitive press. Duplicate taps or multiple team sessions cannot give a team extra positions in the same window; retain the team's earliest valid server press.
- The admin queue refreshes every 750 ms while visible, highlights the current earliest team and confirms answering priority after closure. It displays Asia/Kolkata time with six fractional digits and retained UTC; equal recorded times are held for review, not broken by team code.
- Separate **sending**, **recorded**, **already buzzed**, **closed/paused** and **connection/unknown outcome** states. A button click or local animation is not acknowledgment. A lost response must recover/retry the same press; retries cannot claim an earlier local click time.
- Closing/advancing a window must reconcile admitted/in-flight requests so an earlier server-received press cannot silently disappear behind a later response. Exact equal-timestamp handling, early-buzz penalties and whether the opportunity passes after an incorrect answer remain organizer decisions.

Buzzer priority grants an opportunity to answer, not points. The host records the offline answer/verdict; reviewed scoring follows the approved contract. Staff cancellations or adjudicated exceptions retain original buzz order and a reason/evidence trail. Server/database outage handling and authorized restart/recovery remain required; the participant-latency policy does not waive durable server evidence.

## Content preparation — planned

Assign stable stage/question IDs and versions. Keep the host's presentation pack and private answer key outside Git and participant assets. Record the approved answer and acceptable variants, content verifier, source/provenance reference and scoring-rule version for each item.

- For AI recognition, retain the known origin of each image and a verified selection of AI-generated/non-AI images. Visual appearance alone does not establish the answer key.
- For keyword questions, verify the intended concept and accepted synonyms. The supplied biometrics example illustrates the format, not a complete approved question set.
- For encoded words, retain the original word, encoded form and approved decoding rule; do not choose a cipher without organizer input.
- For abnormalities, retain the expected defect and the reference used to verify it. Avoid treating a normal keyboard-layout difference as an accidental missing key.
- For progressive guessing, prebuild and verify the exact sequence of partial-image reveal steps through the final full image. Keep the full answer image and future reveal steps private before they are presented.

The host may use local slides or another approved offline presentation tool. A website slideshow/reveal controller is a separate feature decision, not included automatically. Rehearse the local display, image legibility, participating smartphones and admin buzzer queue with the event staff.

## Scoring, review and evidence — implemented locally in M13

Reuse the external scoring/publication architecture with a Round 5-specific schema and ranking strategy. Retain original question-level records rather than accepting an unexplained total. The proposed source record identifies stage/question/version, team, the native server buzzer event/window/order, offline answer/verdict, any reveal step, awarded points or penalty, official sequence/time reference and source-sheet/judge evidence. Imports must reference retained buzzer evidence rather than inventing client timestamps or a different first team. Exact columns and required fields depend on the approved scoring rules.

M13 provides bounded CSV/manual validation, native press/host evidence linkage, independently committed ledgers, appended corrections and reviewed provisional/final publication. Another team can answer after an earlier wrong/unanswered response only if it has a native buzz in the queue. Cumulative totals sum final Round 1–4 points and Round 5 credit. Equal totals use the earlier host-confirmed completion of the last credited correct Round 5 answer. One team receives **The Winner of Tech Treasure Hunt**; no Round 6 qualification is produced.

Extend signed inventories/recovery to Round 5 rules, question/reveal versions, buzzer windows/press times/order and staff controls, original score records, reviewed corrections, tie decisions and winner snapshots. Preserve restrictions and session revocation. Do not replay an old press into a newly opened window or reopen a recovered window automatically. A lost source sheet or unresolved disputed buzzer decision must remain a material coverage gap.

## Organizer decisions and placeholders

| Required input | Current value |
|---|---|
| Date, venue, start/end and host/judges | PENDING |
| Confirmed finalist count | PENDING — existing Round 4 plan selects five |
| Questions per stage | CONFIRMED — five; 25 questions total |
| Duration per stage / overall | PENDING |
| Encoding rule and acceptable answers | PENDING |
| Approved images, abnormality keys and reveal sequences | PENDING |
| Buzzer mechanism and first answering opportunity | CONFIRMED — website buzzer; earliest valid server-recorded press answers first offline |
| Participant latency/phone policy | CONFIRMED — participant responsibility; no client-time or network-latency compensation |
| Exact equal-server-timestamp resolution and early-buzz rules | PENDING |
| Answer time limit and who may answer for a team | PENDING |
| Correct/wrong/no-answer points and negative marks | CONFIRMED — correct 1 in stages 1–4, 2 in stage 5; otherwise 0; no penalties |
| Passing after a wrong answer | CONFIRMED — only teams with native buzzes, preserving queue order |
| Reveal timing | Stage 4; reveal sequence still needs content; correct remains 1 mark |
| Stage/round totals | CONFIRMED — 5/5/5/5/10; 30 before reviewed voids |
| Carry-over | CONFIRMED — latest final R1–3 points; R4 provides qualification only and zero points |
| Faulty-question voids and disputed buzzer/answer review | PENDING |
| Score tie-break and winner count | CONFIRMED — earlier last-correct completion; one event winner |
| Exact equal/missing completion-time tie and appeal window | Organizer approval required; no automatic team-code winner |
| Scorekeeper, independent verifier and retained evidence procedure | PENDING |

`PENDING` values are editable planning placeholders. They are not approved scoring, consent or evidence references. Real rule/content approval is required before READY.

## Delivery milestones

- **M12 — complete locally:** Round 5 configuration, information/navigation, Round 4 → 5 eligibility, participant buzzer, durable server ordering and admin window/queue controls. Actual reviewed content/rules remain inputs.
- **M13 — complete locally:** Host completion evidence, reviewed buzzer-linked sources, stage/carried totals and one independently published event winner. Actual private content and final prior results remain required inputs.
- **M14 — complete locally:** Signed buzzer/source/winner exports and recovery, plus host/scorekeeper/smartphone rehearsal procedures. Actual physical rehearsal remains a release gate.
- **M11:** Integrated Round 1 → 2 → 3 → 4 → 5 acceptance, including concurrent presses, timestamp ordering, retries, window isolation, recovery, authorization and winners.

See [milestone status](DEVELOPMENT_STATUS.md) for completed work and the remaining implementation sequence.
