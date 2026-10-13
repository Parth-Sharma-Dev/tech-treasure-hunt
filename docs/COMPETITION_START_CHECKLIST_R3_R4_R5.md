# Competition checklist: Rounds 3, 4 and 5

Check against **https://techtreasurehunt.in** and the production database. Tick
only verified items. Content/controller: **parth**; independent verifier:
**verifier**. Round 5 content is still pending organizer verification and must
remain DRAFT until its actual host pack and rules are independently approved.

## Confirmed format

| Round | Format | Scoring | Progression |
|---|---|---|---|
| 3 | Supervised coding; 45 active minutes | Five tasks, 100 marks | Final R2 qualifiers enter; **11 advance** |
| 4 | Faculty interaction | Green Card yes/no; no numerical criteria | **11 enter; up to 5 advance** |
| 5 | Presentation + website buzzer | **Only Round 5 points**, maximum 30 before reviewed voids | One overall winner |

Round 5: five questions in each of five stages. Stages 1–4 award one point per
correct answer; stage 5 awards two. Wrong: -1 in every stage; unanswered: zero. Early press before host GO: -1 once per team/question. No passing. Earlier
rounds determine eligibility but contribute **no points to the final**. Equal R5
scores use earlier host-recorded completion of the last credited correct R5
answer; any unresolved exact tie needs the approved reserve/review procedure.
R3/R4/R5 use the approved appeal windows; verify the intended five-minute value.

## 1. Shared deployment and access check

- [ ] App Service is running the intended combined release and all migrations are applied.
- [ ] HTTPS certificate, `/login`, `/api/health`, participant dashboard and staff POST actions work on the custom domain.
- [ ] Production points to `tth-event-db-parth.postgres.database.azure.com` / `treasure_hunt`, not a rehearsal copy.
- [ ] Confirm actual database round IDs. Expected current IDs are R3 **8**, R4 **9**, R5 **10**; these are not round numbers.
- [ ] `parth` and `verifier` sign in with MFA in separate browser profiles and have the required permissions.
- [ ] Authenticator devices are charged; recovery codes are retained privately.
- [ ] No pending qualification-impact, recovery or material incident suspends entrants' access. Independently review the TH0097 status decision and any resulting incident closure.
- [ ] Latest R2 FINAL publication contains the corrected eligible qualifiers under the reviewed workbook ranking; provisional results alone do not unlock R3.
- [ ] TH0097 remains ineligible after the reviewed disqualification; the approved replacement is present in the R2 final list.
- [ ] Remove only stale test sessions before participant login. Do not revoke legitimate live sessions.
- [ ] Venue internet/site access, power, spare devices and help desk are ready.
- [ ] Retain a fresh private database backup and the private coding/host packs, signing secrets and required original reports.
- [ ] Azure logs and App Service/PostgreSQL resource metrics are open for the operator.
- [ ] No deployment, load generator or database switch will run during play.

Read-only SSH check from the active application directory with `antenv` active:

```bash
python manage.py shell <<'PY'
from django.db import connection
from django.db.models import Count
from competition.models import Round, CodingTask, BuzzerQuestion
print('DB:', connection.settings_dict['HOST'], connection.settings_dict['NAME'])
for r in Round.objects.filter(is_demo=False, number__in=[3, 4, 5]).order_by('number', 'attempt_no'):
    print('Round:', r.number, 'ID:', r.pk, 'attempt:', r.attempt_no,
          'state:', r.state, 'budget_ms:', r.active_budget_ms, 'cut:', r.advancement_count)
    rules = r.rules_snapshot.get('rules', r.rules)
    print('Ranking:', rules.get('ranking_policy'), 'Schema:', rules.get('score_schema'))
    if r.number == 3:
        print('Coding tasks:', CodingTask.objects.filter(round=r).count(),
              'verified:', CodingTask.objects.filter(round=r, verified_at__isnull=False).count())
    if r.number == 5:
        print('Questions per stage:', list(BuzzerQuestion.objects.filter(round=r)
            .values('stage').annotate(count=Count('id')).order_by('stage')))
PY
python manage.py migrate --check
```

Counts do not establish independent content correctness or physical readiness.

## 2. Round 3 content and lab preparation

- [ ] The private Word content bundle has been imported through the dry-run/apply workflow, not exposed in public assets.
- [ ] Five tasks are present: OUTPUT 15, DEBUG 25, FILL 20, SHORT 30, LOGIC 10; total 100.
- [ ] Participant prompts, language restrictions and starter code match the supplied paper. No private solutions or hidden tests appear in participant content.
- [ ] The ten SHORT hidden tests are correct and preserved with stable H01–H10 IDs; three marks each. Judges have the private rubrics.
- [ ] `verifier` independently verified every task and the current rules before READY.
- [ ] R3 advancement is **11**, despite the original document's superseded top-ten wording.
- [ ] Python **3.13.13**, C compiler **15.2.0** and the agreed C99 command are installed and tested consistently on lab machines.
- [ ] Actual schedule is confirmed. The supplied document says **13 October, 12:00–12:45 PM IST**; published information and announcements agree.
- [ ] Actual lab room, help contacts and supervisor/judging duties are assigned and publicly announced where appropriate.
- [ ] Workstation labels and physical seating are ready for all R2 finalists; one workstation/browser per team.
- [ ] Teams sign out of their old phone/browser before signing in on the lab browser to avoid the single-session limit.
- [ ] Lab supervision enforces no AI, phones, notes, external storage or unapproved internet; access to the contest submission site remains available.
- [ ] The operator knows how to assign the team's current browser to its workstation in `/staff/coding`.
- [ ] A rehearsal confirmed task viewing, acknowledged saves, final locking and staff retrieval on approved lab tools.
- [ ] Tie policy is approved: score, fully correct tasks, earlier recorded final submission; unresolved exact cutoff ties are not decided by team ID.

## 3. Run and judge Round 3

- [ ] Confirm the correct real R3 attempt is READY; open lobby and assign qualified team sessions to their workstations.
- [ ] Start once at the announced time and confirm the shared 45-minute clock. Scheduled information does not itself start the clock.
- [ ] Tell teams to wait for successful save acknowledgments and use **Final submit and lock work** before cutoff.
- [ ] Supervise saves/submissions; local typing or an unacknowledged upload is not durable evidence.
- [ ] End/persist the round at cutoff through staff controls. If the timer expired but admin still says LIVE, run `python manage.py end_expired_rounds --actor parth`.
- [ ] Judges evaluate the exact frozen source in the lab; the website does not execute code.
- [ ] OUTPUT/DEBUG/FILL/LOGIC are all-or-nothing. SHORT marks use the actual passed hidden-case IDs, not hand-entered arbitrary totals.
- [ ] Retain execution references and supervisor time evidence; independently approve all required judgments.
- [ ] Publish provisional results, resolve incidents/cutoff ties, wait the full appeal window and independently finalize **11 qualifiers**.

## 4. Round 4 preparation and execution

- [ ] R3 latest FINAL qualifiers contain the intended eleven entrants; no predecessor incident blocks them.
- [ ] R4 uses EXTERNAL / `round4-green-card-v2`, `green_card_qualification`, cut **5**, zero carried points.
- [ ] There is no fixed question bank or numerical criterion form. Faculty make Green Card yes/no decisions.
- [ ] Existing faculty names/roles are correct and independently published with consent reviewed; portraits/initials avatars are not displayed.
- [ ] Actual venue, interview timing, faculty availability and help contacts are confirmed and published.
- [ ] All eleven eligible teams can find their faculty/interview instructions; any physical allocation is communicated clearly.
- [ ] Independently approve current R4 rules and mark READY before opening/start.
- [ ] Record the complete signed/reviewable Green Card recipient list using official team IDs; no duplicates or unknown/unqualified teams.
- [ ] End R4. At `/staff/scores`, select its exact attempt, enter the complete recipient list and confirm completeness.
- [ ] Dry-run; `verifier` checks the original list and commits. Unlisted eligible teams receive no card; up to five qualify, with no automatic filling of unused places.
- [ ] Publish provisional results, resolve appeals and wait the approved window, then independently publish FINAL recipients.

## 5. Round 5: complete later, before READY

- [ ] Deploy the revised scoring release and apply `configure_round5_only` to the real R5 DRAFT after reviewing its dry run.
- [ ] Confirm schema **round5-v4**, `carry_over: none`, ranking **round5_score_then_last_correct**, no advancement count and one winner.
- [ ] Earlier R1–R4 results/points remain historical; only R5 points contribute to the final standings.
- [ ] Obtain the organizer's verified actual content: exactly five questions per stage, **25 total**. No placeholders remain.
- [ ] Stages match the presentation: 1 AI image recognition; 2 keywords; 3 image abnormalities; 4 progressive image guessing; 5 word encoding/decoding.
- [ ] Every website question ID/version maps to the correct slide and has a private answer, accepted alternatives/judging notes and presentation reference.
- [ ] All images, progressive reveal sequences, answer keys and host packs are privately retained. Unrevealed questions/answers are absent from participant pages.
- [ ] Agree the total active duration, answer opportunity time, passing rules, accessibility arrangements and exact-tie/reserve procedure.
- [ ] Actual offline rules reference, host, recorder, verifier, venue and help contacts are assigned.
- [ ] `verifier` independently checks all questions and the rules; mark READY only afterwards. Later edits require a new attempt.
- [ ] R4 latest FINAL Green Card recipients are the only intended finalists. Confirm they can sign in on one device each and access the buzzer.
- [ ] Rehearse opening, pressing, closing, recording answers and recovery on approved devices/network; separate the rehearsal from official scoring.
- [ ] Final scoring instructions explicitly announce **no carry-over from earlier rounds**.

To apply the revised scoring configuration after deployment, while R5 is DRAFT:

```bash
python manage.py configure_round5_only --actor parth --penalties --dry-run
python manage.py configure_round5_only --actor parth --penalties
```

This does not create questions, approve content, set the actual duration or start
play. Do not mark READY while Round 5 content verification is still pending.

## 6. Round 5 host sequence: repeat for every question

- [ ] Start R5 through `/staff/rounds`; keep `/staff/buzzer` ready on the operator's device.
- [ ] Open the selected question buzzer before reading. After reading, click **Question read complete / GO**, confirm acknowledgment and announce GO. Early receipts cost one point each per team/question and do not enter priority.
- [ ] **Close buzzer and confirm order** before calling the first team. Do not choose from a still-changing open queue.
- [ ] Call teams in confirmed server order. Exact equal buzz times require reviewed priority evidence; do not reorder distinct timestamps.
- [ ] Record the spoken answer, CORRECT/WRONG/NO_ANSWER, host-sheet reference and reason immediately in **Offline answer evidence**.
- [ ] Confirm the save before opening the next question. The host-recorded completion timestamp supplies the score tie-break.
- [ ] Only the first valid post-GO team answers. WRONG costs one point in any stage; NO_ANSWER costs zero. No passing to another team.
- [ ] Stage 4 reveal steps do not reduce its one-point award; stage 5 earns two per correct answer.
- [ ] If a write outcome is uncertain, recover/retry the same saved request before continuing.
- [ ] On an interruption, pause through controls and retain the incident/evidence. A resumed round needs a fresh buzzer window.

## 7. Round 5 score review and winner

- [ ] End/persist the round and close all windows. Retain coverage for every one of the 25 frozen questions, including reviewed voids if needed.
- [ ] In `/staff/scores`, **Load native host records as source drafts** and complete the required outcome for every finalist/window.
- [ ] Use actual CORRECT/WRONG/NO_ANSWER evidence; explicitly record NO_BUZZ/NOT_CALLED where applicable. Never invent presses, answers or completion times.
- [ ] Dry-run and independently commit the complete ledger. The server calculates points from reviewed outcomes.
- [ ] Check stage totals 5/5/5/5/10, maximum 30 before reviewed voids; final total equals R5 points and earlier carry-over is zero.
- [ ] Publish provisional winner standings, resolve source gaps/material incidents/ties and allow the full appeal window.
- [ ] Independently publish FINAL with exactly one reviewed winner. Announce the award only after confirmation.
- [ ] Retain private original host records, reports, checkpoints, decisions and backup after each round.

## Sign-off

- Controller / time: __________________________________________
- Independent verifier / time: ________________________________
- Unfinished item / owner / decision: __________________________
- Round 5 content readiness: **PENDING until actual verified content is supplied**.

References: [R3/R4 import and release](ROUND3_ROUND4_CONTENT_RELEASE.md),
[coding operations](ROUND3_OPERATIONS.md),
[Green Card operations](EXTERNAL_ROUND_OPERATIONS.md),
[buzzer operations](ROUND5_OPERATIONS.md), [R5 scoring](ROUND5_SCORING.md).
