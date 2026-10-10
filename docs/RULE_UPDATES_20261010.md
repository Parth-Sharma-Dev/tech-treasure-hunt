# Current rules — 10 October 2026

These organizer changes supersede the earlier four-digit codes, faculty criterion scoring and 50-mark final for **new attempts**. Released attempts retain their frozen rules, sources and historical results.

| Round | Current behavior |
|---|---|
| 1 | Answer codes are exactly six ASCII letters or digits, case-insensitive; leading zeros are preserved. QR/fallback access codes remain separate from answers. |
| 2 | Import the actual Wayground Excel export. Raw `Score` supplies points; lower `Total Time Taken` breaks score ties. Explicitly map each player to a qualified team or exclude with a reason. Original workbooks are retained. Existing `round2-v1` intake remains legacy support. |
| 3 | Supervised Python/C saves, locked/cutoff work and independently reviewed lab judgment remain unchanged. |
| 4 | Enter only names/codes of Green Card recipient teams. Review the complete list independently. Those teams qualify; unlisted teams receive no card. No faculty criterion marks, numerical ranking or carried points. |
| 5 | Five questions/stage; stage order and point weights below. Sum final R1–3 points plus R5; R4 only supplies qualification. |

## Round 4 operation

Use `score_schema = {"version":"round4-green-card-v2","max_score":"0","qualification_only":true,"carry_over_points":0}` and `ranking_policy = "green_card_qualification"` before READY. Real advancement is capped at five; the two-team demonstration uses cap two. Published faculty information/optional panels are independent of marks.

After ENDED, open `/staff/scores`, select the exact R4 attempt and enter **Green Card recipient team names (one per line)**. Unique team codes also work. Confirm the list is complete: unlisted R3 finalists explicitly get no card. Unknown, ambiguous, duplicate, inactive/unqualified names or too many recipients block commit. A different verifier reviews and commits the source batch; final publication qualifies exactly the eligible recipients, without filling remaining slots from unlisted teams. Corrections append replacement card records; original lists remain retained. Signed recovery includes `greencardrevision` evidence.

## Round 5 order and scoring

| Stage | Topic | Correct/question | Stage maximum |
|---|---|---|---|
| 1 | AI image recognition | 1 | 5 |
| 2 | Answer from keywords | 1 | 5 |
| 3 | Image abnormalities | 1 | 5 |
| 4 | Progressive image guessing | 1 | 5 |
| 5 | Word encoding/decoding | 2 | 10 |

Total **30**; wrong/unanswered remain zero, with no negative marking. Only buzzing teams can answer, in server order after earlier wrong/no-answer responses. Reveal steps belong to stage 4 and do not change marks. A void removes that question's own weight from the effective maximum. One overall winner remains **The Winner of Tech Treasure Hunt**; equal totals use the original host completion time of the last credited correct R5 answer, with exact/missing-time ties held for the approved policy.

The current schema is `round5-v2`, with `points_per_stage = {"1":1,"2":1,"3":1,"4":1,"5":2}`, `max_score = 30` and `carry_over = "sum_final_rounds_1_to_3"`. All four predecessor finals are still required: R4's complete reviewed Green Card qualification must be established, while its carried total is zero. See [full scoring contract](ROUND5_SCORING.md).

## Prepared professor drafts

Unused demo R1 attempt 3 (ID 8), R4 attempt 2 (ID 11) and R5 attempt 2 (ID 12) now use the new rules. They remain DRAFT and require independent content verification/rule approval. R1 demo keys are `AB1024`, `CD0042`, practice `AB0427`. R5 cards are `PROF-S1-Q1` through `PROF-S5-Q5`; the private `.local/PROFESSOR_DEMO_HOST_PACK.md` has revised prompts/answers, including encoded-word fixtures at stage 5. All clocks remain 60 minutes maximum and demo appeals one minute. Existing real/historical records were preserved.

Round 2's professor draft (attempt 2, ID 9) uses `round2-wayground-v2` with eight questions, raw platform points and exported answering duration. It remains DRAFT awaiting independent rule approval; no workbook scores have been imported into this draft. Historical results remain preserved.

## Wayground workbook contract

The supplied workbook has `Participant Data` columns `Player Name`, `Score`, `Total Time Taken` and question counts. Its three rows contain scores 7000, 5390 and 3180; answering durations are 24, 25 and 33 seconds. Excel day fractions are converted to milliseconds. Correct counts and Accuracy are supporting evidence, not points. No genuine game-score maximum is supplied, so the interface displays raw points without a misleading denominator.

Use the score desk after ENDED: upload `.xlsx`, map every exported player to a previously qualified team or explicitly exclude with a reason, dry-run, then have a different verifier commit. Do not create teams from player names. Retained original bytes/checksum and signed recovery bind the calculation to its source. Reject formulas, unfinished grading, inconsistent question counts, missing/duplicate mappings and injected marks. Correct an export through a replacement reviewed batch; the legacy question-void operation does not apply to raw platform points. See [operations](EXTERNAL_ROUND_OPERATIONS.md).

The [M11 acceptance walkthrough](M11_ACCEPTANCE_TESTING.md) and [professor restart guide](PROFESSOR_DEMO.md) follow these changes. M11 and actual device/content rehearsal remain pending.
