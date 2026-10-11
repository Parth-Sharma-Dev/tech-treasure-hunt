# Fast Round 1 and 2 rehearsal on the restored database

Use the restored database only, with three real-cohort mock teams and separate
content-admin/verifier browser profiles. The following configuration releases
one riddle and uses a clearly labeled fabricated Round 2 workbook. It exercises
application scoring, qualification, source review and publication; it does not
certify the remaining clues, actual Wayground export or venue capacity.

## Staff identities and fields

In App Service SSH, from the active application directory with `antenv` activated:

```sh
python manage.py shell -c "from django.contrib.auth import get_user_model; print(list(get_user_model().objects.filter(is_staff=True).values('id','username','is_active')))"
```

Use the content admin's database user ID for technical/content/operations lead and
adjudicator, and the different verifier's ID for verifier. For example only, if
their IDs are 1 and 2:

```json
{"technical_lead":1,"content_lead":1,"operations_lead":1,"adjudicator":1,"verifier":2}
```

Replace these example IDs with the actual production account IDs. Content admin
needs `prepare_content` and `control_round`. Verifier needs `verify_evidence` and
`publish_results`. Both must use MFA on the updated release.

In `/admin/competition/round/`, edit the existing imported DRAFT records. Preserve
their attempt numbers and use these field values:

| Field | Round 1 | Round 2 |
|---|---|---|
| Number | 1 | 2 |
| Title | QR Mission Hunt | Tech Quiz |
| Delivery mode | ONLINE_HUNT | EXTERNAL |
| Rules version | mock-r1-20261011-v1 | mock-r2-20261011-v1 |
| Active budget ms | 900000 | 2700000 |
| Advancement count | 25 | 15 |
| Is demo | Unchecked | Unchecked |
| Owners | Actual staff-ID mapping above | Same mapping |

R1 has a 15-minute mock budget. Real-cohort R2 requires 45 minutes, 30 questions
and cut 15; end it early using normal controls. The short-roster policy below lets
all three eligible teams advance. Require exactly three active real-cohort teams
for this run; local-demo teams belong to a different cohort.

## Round 1 Rules JSON

```json
{
  "allowed_tools": ["Contest website and supervised mock materials"],
  "movement_policy": "Stay at the supervised rehearsal workstation.",
  "route_reference": "mock-run-20261011-supervised-workstation",
  "accessibility_policy": "No campus travel required for this mock; organizer assists as needed.",
  "qualification_tie_policy": "supervised_reserve_clue",
  "appeal_minutes": 1,
  "paper_attempt_policy": "not_applicable_to_this_mock",
  "unresolved_data_policy": "suspend_for_review",
  "retention_days": 30,
  "short_roster_policy": "advance_all_eligible",
  "delivery_instructions": "Mock only: open the released riddle, submit assigned pool codes, retain receipts.",
  "ranking_policy": "score_then_last_active_completion",
  "code_mode": "independent_pool",
  "answer_format": "six_printable_ascii",
  "max_code_claims": 3,
  "points_per_code": 1,
  "expected_code_count": 168,
  "expected_mission_count": 1,
  "max_team_sessions": 1,
  "free_wrong_attempts": 5,
  "cooldown_seconds": [30, 60, 120, 240, 300],
  "team_answer_limit": 10,
  "team_answer_window_ms": 60000,
  "cutoff_policy": "database_admission_no_grace",
  "registration_cap": 3,
  "peak_browser_count": 3
}
```

## Round 2 Rules JSON

```json
{
  "allowed_tools": ["Contest website and supervised mock materials"],
  "movement_policy": "Stay at the supervised rehearsal workstation.",
  "route_reference": "mock-run-20261011-supervised-workstation",
  "accessibility_policy": "No campus travel required for this mock; organizer assists as needed.",
  "qualification_tie_policy": "supervised_reserve_question",
  "appeal_minutes": 1,
  "paper_attempt_policy": "not_applicable_to_this_mock",
  "unresolved_data_policy": "suspend_for_review",
  "retention_days": 30,
  "short_roster_policy": "advance_all_eligible",
  "delivery_instructions": "Mock only: external Wayground-format score import, independently reviewed.",
  "ranking_policy": "wayground_score_then_answer_time",
  "score_schema": {
    "version": "round2-wayground-v2",
    "max_score": "9999999.999",
    "maximum_is_storage_bound": true,
    "question_count": 30,
    "score_metric": "wayground_score",
    "time_metric": "reported_answer_duration",
    "source_sheet": "Participant Data"
  }
}
```

The schema's `max_score` is the database storage bound, not a quiz maximum. Keep
the exact schema; the participant interface hides the misleading denominator.

## Prepare one mission and release both rounds

1. Content admin opens `/admin/competition/mission/`, filters to the correct R1
   and edits `MISSION-01`. Preserve its imported riddle/private clue location.
   Set clue type TEXT, volunteer owner to the content admin for this mock,
   QR location to `Mock workstation QR entry`, Available checked, Is practice
   unchecked. Leave Answer and Keyword empty: codes/keywords belong to the pool.
2. Keep the other 24 missions unavailable. Save the mission before verification.
3. Verifier selects that mission and runs **Attest to independent end-to-end
   mission verification**, after checking its clue and access information.
4. Verifier selects R1 and R2 in the Rounds list and runs **Approve the current
   draft rule settings**. Check both success messages.
5. Content admin selects the same rounds and runs **Validate and mark approved
   rounds READY**. Do not edit configuration/content after approval; edits stale it.

Optional participant-information check: add one Round information record per round
with summary `Round 1 mock rehearsal` / `Round 2 mock rehearsal`, venue
`Supervised mock workstation`, suitable general instructions, Contacts `[]`,
Visible checked and schedules blank. Verifier independently publishes them using
the information list action. Keep answers/codes out of participant instructions.

## Play and publish Round 1

1. Give A three, B two and C one distinct valid codes from the private
   `/admin/competition/huntcode/` list. Do not reuse a code between teams.
2. Each team signs in at `/login` in a separate browser/device. One active browser
   is allowed per team; sign out before switching browser.
3. Content admin opens R1 lobby and starts it on `/staff/rounds`, with explicit
   mock reasons. Teams enter R1 and navigate using MISSION-01's QR token URL
   (`/missions/<token>`) or its fallback code, then click **Open mission**.
4. A claims three codes, B two, C one. Expect scores 3/2/1 and earned keywords.
   Any valid unclaimed code works on this one opened mission. Preserve punctuation.
5. Try replaying an owned code: no extra point. A fourth new code after A's third
   claim is blocked. Pause and verify score-changing attempts are blocked; resume.
6. End R1 and check late submissions cannot add points.
7. In `/staff/results`, content admin proposes PROVISIONAL with summary
   `Mock R1: A=3, B=2, C=1`. Verifier confirms evidence and approves/publishes.
8. Check R2 is still gated. Wait until the displayed one-minute appeal deadline.
   Resolve actual blockers if any; content admin proposes FINAL and verifier
   independently approves/publishes. Expect all three final qualifiers.

## Play, import and publish Round 2

1. Content admin opens R2 lobby. Teams check their R1 keywords on its page.
2. Start R2 and check keywords disappear from that page. For the fast workflow
   mock, use the synthetic workbook; the real quiz is not being administered here.
3. End R2. Content admin opens `/staff/scores`, selects R2 and enters reason
   `MOCK ONLY: fabricated workbook tests the intake and review workflow`.
4. Upload `.local/fast-mock-r1-r2/round2-MOCK-ONLY-30questions-3teams.xlsx` using
   **Read Wayground workbook**. It is clearly labeled fabricated test data,
   not an original Wayground report. Map MOCK Player A/B/C to the actual three
   qualified team codes, then dry-run. Expected points 7000/5000/3000 and answering
   durations 24/31/45 seconds; all rows have 30 questions and complete grading.
5. Verifier reviews this explicitly synthetic source, confirms the mappings and
   commits the reviewed batch. Content admin cannot commit their own batch.
6. Repeat the PROVISIONAL → independent publication → appeal wait → FINAL →
   independent publication sequence. Expect all three qualifiers under the
   short-roster policy, with points and durations visible correctly.
7. Stop here. R3/R5 content is outside this run. Retain a private mock result log
   and signed checkpoints if you want to rehearse evidence capture.

## Finish

Keep the original database and signing keys intact. Return App Service to its
recorded original PostgreSQL hostname when the mock is finished, revoke obsolete
sessions/recovery codes through the recovery procedure and clear saved mock
requests in the test browser profiles. Verify the original round states and
roster. Switching back restores the original database's prior state; the mock's
configuration changes do not populate or configure that original database.

Before tomorrow's real release, prepare every intended mission and configure the
approved real duration, capacity, appeal policy, routes and mission count there.
Use the genuine Wayground export for official R2 scoring. The mock workbook and
one-minute appeal settings are for this isolated rehearsal only.

Validation: both exact JSON configurations passed readiness, rule approval and
READY transition checks in the isolated PostgreSQL test database using the actual
imported private content. The synthetic workbook passed the real workbook parser.
No production or local event gameplay state was changed by that check.
