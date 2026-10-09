# Round 5 scoring and the event winner

The organizer supplied these rules during M13: five questions in each of the five stages, two marks per correct answer, zero for wrong/unanswered, no negative scoring, passing to teams that buzzed, carry-over scores and one winner. Answers and judging remain offline; source review and publication take place on the website.

## Confirmed contract

| Item | Rule |
|---|---|
| Question count | 5 per stage × 5 stages = 25 |
| Marks | Correct = 2; wrong/unanswered = 0; no penalties |
| Stage total | 10 |
| Round 5 total | 50 before independently reviewed global question voids |
| Answer passing | Only to teams with retained native buzzes, in server-recorded order, after earlier teams are wrong/unanswered |
| Carry-over | Sum each finalist's latest published final scores from Rounds 1–4, with no normalization or weights |
| Winner | One team: **The Winner of Tech Treasure Hunt** |
| Ranking | Cumulative score, then earlier host-confirmed completion of the last credited correct Round 5 answer |

All four earlier rounds must have final, reviewed results in the same cohort. Missing scores are coverage gaps, never implicit zeros. A material incident or changed prior qualification/results blocks or stales dependent review.

The completion timestamp is the server time when the host records the observed offline answer, before contended scoring locks. It is distinct from the team's buzzer timestamp and from the later reviewer/import time. Host records must be made immediately after the response, before opening the next question. Client/imported completion times are not accepted.

Equal totals with equal or unavailable last-correct times remain unresolved. Team-code display order never chooses a winner. The frozen exact-tie policy either blocks final awards or requires independently reviewed reserve-question evidence. The local preparation command defaults to blocking exact unresolved ties; the organizer must approve any secondary procedure before READY.

## Configure before READY

Use **BUZZER** delivery and retain the existing owner/content/clock controls. Real attempts need exactly five verified questions in each stage. Leave advancement count empty. Add this confirmed contract to draft rules:

```json
{
  "ranking_policy": "cumulative_score_then_last_correct",
  "score_schema": {
    "version": "round5-v1",
    "questions_per_stage": 5,
    "points_per_correct": 2,
    "wrong_points": 0,
    "unanswered_points": 0,
    "max_score": 50,
    "answer_passing": "buzzer_queue",
    "winner_count": 1,
    "carry_over": "sum_final_rounds_1_to_4",
    "tie_break": "last_correct_completion"
  }
}
```

The schema must match these supplied rules; arbitrary marks, negative penalties or reveal-dependent scoring are rejected. Progressive image guesses still earn two marks at any reveal step. Reveal steps can be retained as source evidence but do not alter credit.

Rules/content remain frozen after READY. An already released M12 buzzer-only attempt with five demo questions cannot acquire a different scoring contract in place; use a new reviewed attempt.

For unsigned local preparation:

```powershell
.venv/Scripts/python backend/manage.py seed_buzzer_scoring_demo --actor DEMO-content
```

This requires a demo BUZZER Round 5 DRAFT. It adds only missing unverified question placeholders up to five per stage, preserves existing questions, sets the supplied contract and invalidates stale rule approval when configuration changes. It never creates prior results, qualification, answers or scores. Repeating it preserves the prepared set. Actual question material and host rules still require independent verification.

## Record the live offline response

1. In `/staff/buzzer`, open the frozen question and let teams buzz. Close the window to confirm the order.
2. Under **Offline answer evidence**, choose the responding team, record the original spoken answer, observed verdict, private host-sheet reference and reason. Click **Record observed offline answer** immediately.
3. The backend checks the current closed window, live clock, original earliest native receipt and earlier respondents. A lower-priority team may respond only after all earlier teams are recorded WRONG or NO_ANSWER. A CORRECT response closes the answering opportunity for later teams.
4. Equal buzzer times need the complete queue order and a private adjudication reference; different timestamps cannot be reordered. Preserve that order when recording subsequent respondents.
5. Resolve an unknown write by retrying the same request before moving to another question. Host evidence is immutable and replayable; changing a judgment later uses reviewed ledger revisions rather than a new completion time.

These are original observations, not published points. Each team/window has one host record. The participant API cannot write host verdicts or inspect private answers.

## Review sources after ending the round

Use `/staff/scores?round=<DATABASE_ROUND_ID>`. End/persist Round 5 first. CSV and manual rows share bounded validation and the independently committed batch workflow.

Required columns:

```csv
window_id,team_code,press_id,answer_evidence_id,verdict,answer,reveal_step,buzzer_tie_order,adjudication_reference,source_reference
```

Use **Load native host records as source drafts** to populate known native IDs and original observations. Complete all remaining rows explicitly; no unobserved verdict is fabricated. For every included window, supply one row for every Round 4 finalist:

- `CORRECT`, `WRONG`, `NO_ANSWER`: reference the exact earliest native press and host record, retaining the original answer text. Marks are calculated by the server.
- `NO_BUZZ`: no native receipt or host record exists for this team/window.
- `NOT_CALLED`: a receipt exists but the team was not given an answer opportunity.
- `VOID`: cancel the question window for **all** finalists with retained adjudication evidence; original buzzes/answers remain intact. The effective maximum is reduced equally when no valid window remains for that question.

Blank native IDs are appropriate only where no corresponding record exists. `reveal_step` is 0–100 in stage 5 and zero elsewhere. `buzzer_tie_order` uses `|`-separated team codes; all rows preserve the same adjudicated order. Private references are bounded to 200 characters and original answers to 2,000 characters. CSV input is limited to 1 MB and source batches to 2,000 rows.

Dry-run does not award points. A different authorized verifier checks every native receipt, original response, completion time, source reference and carry-over basis, then commits the complete batch atomically. Invalid, stale, duplicate or incomplete sources cannot partly change scores. Replay uses the original action UUID.

Corrections append revisions linked to the prior window ledger. Overturning a host verdict or suppressing a recorded response needs retained adjudication evidence; it cannot fabricate a new answer or completion time. A retry of the same question requires reviewed voiding of superseded windows so one question never earns credit twice. Rejected/pending batches remain auditable.

## Publish the winner

Use `/staff/results` for independent provisional/final publication. Public entries contain five stage totals, Round 5 total, carried points, cumulative total and last-correct completion time; answers, native receipt IDs and private sheet references remain staff-only.

Final awards require all 25 frozen questions and every retained window to have reviewed play/void coverage, reproducible sources, final carry-over results, no material gaps/pending batches, the full appeal window and two-person review. Changed points/order require revised provisional results and renewed appeals.

The final snapshot stores one `winner_codes` entry and the event title. `qualifier_codes` is empty; no Round 6 access is created. Historical awards are retained. A later material incident marks the award under review without silently promoting another team. Ordinary edits/imports cannot replace finalized awards.

M14 implements [signed native export/reconciliation](EVIDENCE_RECOVERY.md) of host evidence, ledgers, original timing and winner history with exact carried-result dependencies. Use the [host/scorekeeper rehearsal procedure](ROUND5_REHEARSAL.md). Full competitive-chain, load/outage and actual event rehearsal remain **M11** and organizer release work.
