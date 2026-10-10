# Round 5 host, scorekeeper and recovery rehearsal

M14 local procedure, 9 October 2026. Physical rehearsal is **pending**. Fill the [rehearsal record](templates/ROUND5_REHEARSAL_RECORD.md) with actual people/devices/content and private evidence; placeholders do not approve the event. Use [buzzer operations](ROUND5_OPERATIONS.md), [scoring](ROUND5_SCORING.md) and [signed recovery](EVIDENCE_RECOVERY.md).

## Assign and prepare

| Responsibility | Assignment until supplied | Record |
|---|---|---|
| Host/presentation | PLACEHOLDER — organizer assignment pending | Approved private pack/version, reveal sequence and answer rubric |
| Buzzer controller | PLACEHOLDER — organizer assignment pending | Correct cohort/attempt, question/window IDs, closure and confirmed queue |
| Scorekeeper/maker | PLACEHOLDER — organizer assignment pending | Original host-sheet references and explicit per-finalist question rows |
| Independent verifier | PLACEHOLDER — different authorized staff required | Source/coverage review, publication and recovery permission |
| Technical/incident lead | PLACEHOLDER — organizer assignment pending | Backup custody, separate recovery database and outage disposition |

Prepare 25 independently verified questions, five per stage: AI image recognition, keyword answer, image abnormality, progressive partial-image guessing and word decoding. Match private presentation files to frozen public IDs/version references; record each reveal step in the host sheet. Each correct answer earns one mark in stages 1–4 and two in stage 5; reveal timing does not change marks; wrong/unanswered earns zero. Use actual approved accessibility, response-time, tie and appeal procedures. Confirm final reviewed Round 1–4 results and Round 4 finalists before release.

Each team uses its authorized phone/session. Test the large buzzer, acknowledgment and reload recovery on actual devices at the venue. All teams use the announced network conditions. Server admission time decides priority; device tap clocks and network latency are not compensated. Record device/browser/network details and accessibility issues without collecting passwords or cookies.

## Run every question

1. Host announces the frozen stage/question ID and presents the matching offline content. Controller checks attempt/question and opens a fresh versioned window at the agreed point in the presentation.
2. Teams press. A pending indicator is not proof of admission; wait for the server receipt. After an unknown response, recover the same UUID/window rather than creating a new press. The admin's current earliest team can change until closure drains admitted transactions.
3. Controller closes the window and confirms its persisted queue before the host calls a team. Equal recorded times require retained reviewed priority evidence; never choose alphabetically or estimate phone latency.
4. Host hears the answer offline. Record the verdict, answer/reference and original server confirmation immediately, before opening another window. A wrong/no-answer can pass only to the next team that buzzed. A correct answer ends passing; non-buzzing teams cannot answer for credit.
5. Scorekeeper retains one row per finalist/window, including NO_BUZZ or NOT_CALLED where appropriate, exact press/host IDs, reveal step and original source reference. Unresolved priority or verdict disputes become material incidents.
6. At ENDED, validate the native-linked source draft/CSV. A different verifier checks all 25 questions, queue passing, voids/corrections and prior carried totals, then commits. Publish provisional results, complete appeals and independently publish the single overall award. Tie order uses the original host confirmation of the last credited correct answer; exact/missing-time ties need the approved adjudication policy. Retain original sources when correcting; never backdate completion.

## Interruptions and recovery

Pause/end through round controls when the website/database or presentation cannot continue safely. Controls close the current window. Retain question/version, last confirmed receipts, host sheet, incident time/reference and what is unknown. A verbal buzz, cached click or spreadsheet timestamp cannot replace missing server evidence. Record unproved intervals as unresolved; the website has no Round 5 paper buzzer mode.

After an application restart with intact PostgreSQL evidence, reload the exact attempt and check its persisted state, current window and original receipts. A restart does not itself close a still-valid LIVE window; deliberately close/pause it before an interrupted presentation resumes. Resuming a paused round needs a fresh explicit window. Approved retries retain old windows; only one reviewed non-void ledger may credit a question.

For database loss, preserve the source and restore a signed database backup into a new isolated `tth_recovery_*` database. Stop all cohort play before per-round reconciliation. Recover the original earlier-round dependencies first, then propose a signed v3 Round 5 checkpoint. Independently check missing/changed/additional evidence, sessions/restrictions, exact original timings, ledgers and winner history. Missing press sessions become revoked tombstones; no old cookies or automatically open windows are restored. Resolve baseline incidents and all intervals after the checkpoint separately. Do not promote the recovered database or issue credentials until that operational decision is approved.

## Required rehearsal cases and acceptance

| Case | Evidence and expected result |
|---|---|
| Two or more simultaneous phones | Closed queue preserves database-time priority; confirm precision and host call |
| Double tap, lost response and reload | Same receipt/window recovered, one effective team position and no duplicate credit |
| Wrong answer then next buzzing team | Native host evidence follows queue; no unbuzzed team receives marks |
| All five stages and progressive reveals | Frozen presentation versions match IDs; five questions/stage; reveal does not change the stage’s point weight |
| Pause, stale tab and fresh window | Old window rejects new press; unresolved cached request cannot migrate to a new question |
| Application restart | Original receipts survive; operator explicitly inspects/closes interrupted live window |
| Older database plus signed checkpoint | Exact native evidence and historical winner recovered, all sessions revoked and windows closed |
| Missing prior results or conflicting completion | Recovery stays blocked with a material incident; no guessed scores/timestamps |
| Withdrawn/disqualified finalist | Restriction survives restore; historical award is retained for review without promotion |
| Scoring, appeal and award | Carry-over plus up to 30 Round 5 marks; R4 contributes zero, original tie time, exactly one reviewed event winner |

A rehearsal passes only when the actual evidence references, maker and independent verifier are recorded, all coverage/accessibility issues have an explicit disposition and no material gap remains. Local synthetic/browser results support development; they do not certify venue phones, load or a physical event rehearsal. Broader full-event acceptance remains M11.
