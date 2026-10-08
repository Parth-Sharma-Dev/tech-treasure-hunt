# M7 participant portal

Implemented 8 October 2026. M7 provides the participant information portal and round-specific navigation. M8's native Round 3 workspace and lab judging are now implemented; see [Round 3 operations](ROUND3_OPERATIONS.md). External Round 2/4 score entry/publication remains M9.

## Participant experience

After login, `/lobby` displays the latest attempt of each round in the team's demo/live cohort. Cards show round status, eligibility, reviewed overview, venue, schedule in IST, countdown where applicable and published-result availability.

Rounds 1–4 have **Open Round N** information links. These remain useful before/after active play; entering a page does not grant participation. Round 5 has a “Details to be announced” card with no entry action, and its direct overview endpoint returns 404.

Each round page shows global and round-specific organizer announcements, reviewed schedules/venues and approved contacts. Eligible teams can read released activity instructions and approved rules from READY onward. Draft or ineligible teams receive public overviews and a specific eligibility reason, without restricted instructions. Active controls require LIVE plus eligibility; expired clocks are treated as ended.

- Round 1 retains practice, progress, receipts and live online fallback access. Existing QR/login return links still work.
- Round 2 shows event guidance, retained non-voided keywords from the latest Round 1 attempt, and published results when available. Keywords do not add points.
- Round 3 provides approved supervised Python/C information and links to its native coding workspace when the attempt is released and the team is eligible. Only the supervisor-assigned session can save code.
- Round 4 provides interview guidance and approved contact names/roles/locations/channels. Faculty photos, panel/team assignments and criterion scoring are M9 work.

Published results remain readable in the same cohort after a round closes, including by teams that did not qualify. Round information pages use the current attempt; prior publications remain accessible at their historical results URLs.

## Prepare and publish information

Use the existing Django admin and organizer accounts:

1. As `DEMO-content` (or an account with `prepare_content`), open [Round information](http://127.0.0.1:5173/admin/competition/roundinformation/).
2. Add an information record for the intended round attempt. Enter the public summary, general participant instructions, venue, start/end schedule and approved contacts. Supply actual dates and approved public contact details; omitted details appear as “To be announced.”
3. Save the draft. The preparer is recorded automatically. Previously published information remains visible while the revision awaits review.
4. In a separate browser profile, `DEMO-verifier` (or an account with `verify_evidence`) inspects the draft record and its previous published snapshot.
5. On the information list, select the intended record, choose **Independently review and publish selected information**, and click **Go**. Self-publication is rejected even for a superuser.
6. Check the appropriate participant round page. A draft publication exposes only its public overview/schedule/contacts; activity instructions remain state/eligibility gated.

Contacts use this JSON structure; these are placeholder values:

```json
[
  {
    "name": "Approved organizer name",
    "role": "Technical help desk",
    "location": "Approved desk location",
    "channel": "Approved public contact channel"
  }
]
```

The schema supports up to 30 contacts and validates names/roles/text lengths. Contacts render as text, not arbitrary HTML or executable links. Keep clues, answer keys and interview questions out of information records.

Schedules/logistics are independently published separately from the competition's frozen rule snapshot. Editing information after READY does not alter approved scoring rules or the actual round clock. Times are stored as timezone-aware timestamps and displayed in Asia/Kolkata.

To withdraw a published information record, set **Visible** to false in the draft, save, then have a different verifier publish that change. Toggling a draft field alone does not retract the previous publication.

## Announcements

Use [Event announcements](http://127.0.0.1:5173/admin/competition/eventannouncement/) with the same preparation and independent publication workflow. Choose the correct **Is demo** cohort. Leave **Round** blank for a global announcement on the dashboard and all in-scope pages; select a round for notices inside that round's page. A selected round must match the announcement's cohort.

Draft announcements and unreviewed edits are hidden. Published notices remain visible until a separately reviewed withdrawal. Published records cannot silently move between rounds or cohorts. Information publication and withdrawal are recorded in immutable audit events.

## API contract and guards

| Endpoint | Behavior |
|---|---|
| GET /api/rounds | Authenticated team's latest round cards, released information, capability flags and global announcements |
| GET /api/rounds/{id}/overview | Current same-cohort round information, redacted instructions, precise eligibility reason, capabilities, scoped announcements and relevant own keywords |
| GET /api/rounds/{id}/results | Existing immutable published standings/history; no private previews |

Both new endpoints require a valid team session. Cross-cohort/unknown/Round 5 overview IDs return 404; an older attempt returns 409 with guidance to the dashboard. Withdrawn/disqualified and unqualified teams can read approved public information but cannot enter activity. A reviewed release is bound to its cohort; changing a draft round's cohort requires information to be reviewed again.

Capabilities distinguish reading information/results from participating. `open_mission` requires Round 1 ONLINE play; `submit_code` requires native Round 3 LIVE play, eligibility and the current assigned browser session. Backend activity endpoints enforce their own permissions, state and eligibility regardless of hidden frontend buttons.

## Validation and setup

M7 added eight PostgreSQL tests for publication, revisions/withdrawal, invalid schedules/contacts, cohort separation, latest-attempt protection, direct URL guards, team sessions and expired activity. Four new browser scenarios run on desktop and mobile: dashboard navigation/schedule/announcements, ineligible Round 3 redaction, ended Round 2 result access and Round 5 direct URL rejection.

Final regression: **133 backend tests passed** with real-browser Round 1 integrations enabled; one opt-in load test was skipped (its earlier separate run remains recorded). **66 frontend browser checks passed**. TypeScript/build, Ruff, Django checks and migration drift checks passed.

Migration 0010 is applied to the local application database. A signed PostgreSQL backup is retained privately at `.local/m7-before-migration-20261008.dump`. Round states, attempts, scores and competition settings were preserved.

Demo information drafts are prepared for Rounds 1–4 without overwriting existing information or publishing it. Round 3/4 descriptions and scheduled times come from the supplied manual images. Their draft year is 2026 based on the Tech-Pravah 26 context; confirm it before publishing. Venues and contact names remain unfilled because they were not supplied. Review these drafts as the separate verifier before they appear to participants.
