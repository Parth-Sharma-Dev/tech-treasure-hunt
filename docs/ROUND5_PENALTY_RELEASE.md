# Round 5 penalty rules: organizer revision, 13 October

This supersedes the earlier zero-penalty/passing instructions for the new real
Round 5 DRAFT. Frozen historical attempts keep their original contracts.

| Outcome | Points |
|---|---:|
| Correct, stages 1–4 | +1 |
| Correct, stage 5 | +2 |
| Wrong, any stage | -1 |
| No answer / declined | 0 |
| Early buzz before the server-recorded host GO | -1 once per team/question |

Only the first valid post-GO buzzing team may answer. There is **no passing**
after wrong/no answer. An early team can buzz again after GO, but its early
penalty remains. Wrong and early penalties add: an early team that later answers
wrong loses two points. Totals can be negative. Only Round 5 points determine
the winner; earlier scores do not carry over.

## Deploy and configure

Deploy the penalty-enabled website ZIP. In the new active App Service SSH
directory with `antenv` active, confirm the original server/database, then:

```bash
python manage.py migrate --noinput
python manage.py migrate --check
python manage.py configure_round5_only --actor parth --penalties --dry-run
python manage.py configure_round5_only --actor parth --penalties
```

Migration 0024 adds immutable host GO records and an early flag to receipts.
Existing receipts default to not early. The helper requires the latest real R5
to remain DRAFT, sets `round5-v4`, clears stale approval and does not create
questions or start play. Reverify the actual offline rules and independently
approve before READY. Take a fresh private backup/checkpoint after migration.

## Host: per-question sequence

1. Select the correct frozen question and **Open question buzzer** before reading.
   The participant button is available, but pressing while the host is reading
   creates an early receipt and one penalty. Early receipts never enter priority.
2. Finish reading, click **Question read complete / GO**, confirm its acknowledgment
   and announce GO. This server-timed control is the authoritative cue; software
   cannot infer the exact last spoken word. Participants wait for this cue.
3. **Close buzzer and confirm order**, then call only the first valid team. Exact
   equal timestamps still require reviewed priority evidence.
4. Record CORRECT/WRONG/NO_ANSWER immediately, confirm the save and proceed to
   the next question. The desk no longer offers passing after an answer.

A repeated early request cannot multiply the penalty. Retrying its original UUID
preserves the original early outcome even after GO. Before/after GO follows
database admission timing, not a phone clock or estimated network latency.
Paused, expired, obsolete or closed-window requests are rejected without a new
early charge. A reopened retry is a new window; the reviewed ledger must void
superseded windows so one question never contributes twice.

## Score review

After ending, load native host records in `/staff/scores`. Nonresponding teams
are prefilled from native coverage where unambiguous; the first team's outcome
still requires an actual host record. NO_BUZZ means no **valid** buzz; an early
receipt can still supply its independently derived penalty. Early penalties
are calculated from retained receipts and GO records, not manually typed points.

The different verifier reviews and commits the complete ledger. A global question
void removes that window's points and penalties equally; an interrupted window
without GO requires reviewed voiding before final awards. Only correct answers
supply the last-correct completion tie-break; negative wrong points do not.
Publish provisional results, resolve incidents and wait the approved appeal
window, then independently publish one final winner.

## Participant announcement (send after deployment/configuration)

```text
📢 Updated final-round rules:
Correct: +1 in stages 1–4, +2 in stage 5. Wrong: −1 in every stage.
Wait until the host finishes reading and announces GO. Early buzz: −1 once per team/question.
Only the first valid buzzing team answers. No passing after wrong/no answer.
Only Round 5 points count; earlier scores do not carry over.
```
