# Round 5: website buzzer and offline answers

Implemented locally in M12–M14 on 9 October 2026. All five stages use the same buzzer; presentation and answers remain offline. M13 adds host completion records, reviewed ledgers, cumulative scores and one winner. M14 adds [signed native recovery](EVIDENCE_RECOVERY.md) and the [host/rehearsal run sheet](ROUND5_REHEARSAL.md). See [scoring instructions](ROUND5_SCORING.md) and [remaining inputs](ROUND5_FORMAT.md).

## Prepare an attempt

1. Prepare Round 5 with **BUZZER** delivery and an explicit approved active budget. Leave advancement count empty because this is the final.
2. In Django admin **Buzzer questions**, add stable public question IDs, stage 1–5, version, private source reference and private content. The latter requires an `answer` and `presentation_reference`; it can retain encoding/provenance/reveal references as additional private metadata. Actual images and host packs stay private, outside Git/public assets.
3. A different authorized verifier checks the content. Edits, including partial updates, invalidate verification. M13's scoring contract requires exactly five questions per stage; the original five-question M12 demo is buzzer-only. Prepare 25 verified questions for scored play.
4. Configure the shared owner/accessibility/appeal/retention rules and an `offline_rules_reference` identifying independently reviewed answer/scoring/tie procedures. The supported buzzer policies are below. Real attempts reject marked placeholder source/rules references; actual scoring and content still require human verification.
5. Have the verifier approve the rules and the controller mark READY. This freezes the question set and private versions. Revisions after READY require a new attempt.
6. Independently finalize real Round 4 qualification before opening the Round 5 lobby/start. Only active same-cohort qualifiers in the latest attempts may participate; recovery/qualification-impact incidents suspend access.

| Rule field | Supported value |
|---|---|
| `buzzer_order_policy` | `database_receipt_time` |
| `buzzer_latency_policy` | `no_compensation` |
| `buzzer_equal_time_policy` | `staff_review_required` |
| `buzzer_early_policy` | `reject_closed_window` |
| `offline_rules_reference` | Actual approved host/rules reference; synthetic/PENDING values are local demo placeholders only |

Closed/early presses are rejected. Exact equal recorded buzz times are held for reviewed priority; team code never breaks them. Current rules award one per correct answer in stages 1–4 and two in stage 5 word encoding (30 total), zero otherwise, allow queue-based passing and carry final R1–3 points into one event award; R4 Green Cards contribute zero. Reveal steps do not change marks.

For local unsigned preparation:

```powershell
.venv/Scripts/python backend/manage.py seed_buzzer_demo --actor DEMO-content
```

This DEBUG-only command prepares five **unverified** demo questions and an unpublished information draft. It uses a labeled synthetic five-minute budget, preserves existing question sets/released rounds and never creates Round 4 qualification, scores or approvals. Replace real content and policy placeholders before release. The source Round 5 remains DRAFT until reviewed.

## Operate the buzzer

Use `/staff/rounds` to open the lobby/start, and `/staff/buzzer` for question controls and the queue. Staff need `control_round` to change windows; other authorized results roles may inspect the queue.

1. Select the exact Round 5 attempt. Choose a frozen question, supply a reason and click **Open question buzzer**.
2. Participants open Round 5 from their dashboard and press its large buzzer. CSRF is prefetched before enabling it, so the press sends one network request. The page polls window/status changes every 750 ms while visible.
3. The admin sees one effective position per team, ordered by precise server timestamps. While the window is open, **Current earliest team** can still change if an earlier admitted request is completing.
4. Click **Close buzzer and confirm order** before calling the first team. Closing waits for admitted press transactions to finish, then preserves the complete window. **First team to answer offline** identifies the earliest team; equal times instead display a staff-review alert.
5. Record the offline answer immediately under **Offline answer evidence**, before the next question opens. The server captures completion time. Wrong/no-answer permits the next buzzing team to respond; a correct response stops passing. These observations need independent ledger review before awarding points.
6. Select the next question and open a new window. Reusing a question for an approved retry also creates a new version; it never deletes older presses. Round pause/end/extension closes the current window. Resume requires the host to open a fresh window.

A control changed through another reviewed workflow invalidates the old window's round version, even if no explicit closure was recorded at that moment. Such a stale window cannot accept presses; opening the next window closes and retains it.

## Timestamp and recovery behavior

The timestamp is PostgreSQL `clock_timestamp()` at successful buzzer admission, after authentication and a nonblocking shared window gate, **before waiting on the team lock**. All application processes use the same database clock. Browser click times, device clocks and estimated network delays are ignored. This is a server admission timestamp, not a measurement of a physical tap or TCP packet arrival.

Staff closure/round controls take the exclusive window gate before round/team locks. This prevents new admissions during transition and waits for admitted transactions to commit. Native tests demonstrate an earlier press retaining priority even when a later press commits first. Display retains six fractional timestamp digits in IST and the original UTC value; this preserves recorded precision and does not claim device/network timing accuracy.

Every request carries a press UUID and window ID. Same-request replay returns the exact stored receipt, including after closure. Different taps/sessions retain original receipts but count only once per team/window, using the earliest valid receipt. `admitted_at` records the final validation time before insertion; successful acknowledgment is returned after transaction commit. Client timestamps and supplied team identities are rejected. Closed/stale windows, pauses/end, ineligible teams and revoked sessions cannot create new presses.

After an unknown response, **Recover saved press** checks the original receipt first and, if absent, retries the original UUID/window. It survives reload and never converts a press for one question into a new question's press. A transition-in-progress response preserves the unresolved request. A definitive closed-window rejection cannot backdate a locally cached click. Server/database failures require retained evidence and operational review; M14 signed reconciliation retains original buzzes and host times, requires exact carried results, revokes sessions and keeps restored windows closed. See [recovery instructions](EVIDENCE_RECOVERY.md).

## Implemented API routes

| Route | Purpose |
|---|---|
| `GET /api/rounds/{id}/buzzer` | Own eligibility, current visible window and earliest own receipt |
| `POST /api/rounds/{id}/buzzer/press` | CSRF-protected `{action_id, window_id}`; server derives team/time |
| `GET /api/rounds/{id}/buzzer/presses/{uuid}` | Recover an exact own receipt; another team's receipt returns 404 |
| `GET /api/staff/buzzer/rounds` | Authorized buzzer attempt list |
| `GET /api/staff/rounds/{id}/buzzer` | Ordered queue, tie flag, frozen question labels and up to 100 retained windows |
| `POST /api/staff/rounds/{id}/buzzer/control` | Authorized open/close with UUID, reason, expected round/window versions and question ID for open |
| `POST /api/staff/rounds/{id}/buzzer/answer` | Authorized original answer/verdict/reference and native press; completion time comes from the server |

Participant responses contain no private question packs, answer keys, other teams' timestamps or session cookies. Admin queue responses contain question identifiers and timing, not private answers/images. Private content preparation remains in restricted Django admin.
