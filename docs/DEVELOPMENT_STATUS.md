# Development milestone status

Updated 9 October 2026 after M12 implementation. The Round 5 website buzzer and admin queue are implemented locally; answers remain offline. Actual event approval and production release remain separate.

| Milestone | Status | Scope |
|---|---|---|
| M1–M5 | Completed locally | Django/PostgreSQL/React foundation, evidence/rules schema, team sessions, lobby/practice, round controls and durable Round 1 scoring. |
| M6 | Completed locally | Reviewed Round 1 alternate answers/voids, score/time recalculation and post-final qualification-impact review. |
| M7 | Completed locally for original scope | Participant dashboard and Round 1–4 information/activity pages, release controls and eligibility gates. Round 5 navigation is new M12 work. |
| M8 | Completed locally | Supervised Round 3 tasks, revisioned saves, locked/cutoff submissions, lab judging and reviewed qualification. No website code runner. |
| M9 | Completed locally for original scope | Round 2/4 external scores, faculty/panels, Green Cards, Round 2 → 3 → 4 progression and reviewed roster administration. Round 5 scoring is new M13 work. |
| M10 | Completed locally for original scope | Round 1–4 signed evidence exports, reviewed recovery, retained paper reconciliation and isolated backup/restore rehearsal. Round 5 recovery is new M14 work. |
| M11 | Remaining; partial regression coverage | Full five-round journey, concurrent server-ordered buzzes, duplicate/retry/window guards, winners, outages/restarts, load and accessibility/smartphone checks. |
| M12 — Round 5 setup, eligibility and website buzzer | Completed locally | Verified/frozen five-stage private content, information/navigation, final Round 4 qualifier gates, participant buzzer, durable database timestamps/order, replay recovery and admin window/queue controls. Answers remain offline; actual content/rules are pending. |
| M13 — Round 5 scoring and winners | Planned; not implemented | Offline answer/verdict records linked to native server buzzer evidence, CSV/manual validation and independent commits, stage totals, ranking/ties, corrections, appeals and final winners. |
| M14 — Round 5 recovery and rehearsal | Planned; not implemented | Signed buzzer window/press/source/winner inventories and recovery, host/admin/scorekeeper procedures and smartphone rehearsal evidence. |

Keep existing milestone numbers. **M1–M10 and M12 are complete locally.** Continue with **M13 → M14 → finish M11**. Individual regression checks continue throughout; integrated acceptance closes after Round 5 scoring/recovery and the complete event journey are implemented.

## Round 5 scope

The final has five stages: AI-generated image recognition, answer from keywords, word decoding, image abnormalities and progressive image guessing. Teams press the website buzzer; the admin sees server press times and closes the window to confirm the earliest valid team's offline answering opportunity. No client-time or latency compensation is applied. See [Round 5 operations](ROUND5_OPERATIONS.md) and [remaining inputs](ROUND5_FORMAT.md).

M1–M10 retain their completed status for the delivered Round 1–4 scope. The new requirements do not imply Round 5 is already supported by those services.

## Existing validation and remaining release work

M10 recorded 201 backend tests passed, one opt-in load test skipped, 100 desktop/mobile browser checks passed, supplementary focused recovery/placeholder checks and an isolated PostgreSQL restore. See [test evidence](TEST_EVIDENCE.md). Those results do not certify Round 5 or the complete five-round event.

M12 adds **213 passed / 1 skipped** in the full backend suite and **112 passed** in the full desktop/mobile browser suite. A fifth actual Django HTTP/PostgreSQL browser journey covers window opening, a press with a deliberately lost acknowledgment, reload/recovery, confirmed closure and a second question. Concurrency tests verify server-time order survives reversed commit order. Native score/winner acceptance remains M13 and signed buzz recovery remains M14.

Actual tasks/images/answer keys, faculty/hosts/consent, rosters, schedules, venue/network/buzzer procedures, appeal policies and scoring decisions remain organizer inputs. Existing hidden faculty drafts and the [organizer data template](templates/ORGANIZER_DATA.md) provide placeholders. Hosting/TLS, deployed capacity, actual devices/campus checks and physical rehearsal remain separate release gates.
