# Development milestone status

Updated 9 October 2026 after the Round 5 format was supplied. Local implementation and recorded validation are distinguished from actual event approval and production release.

| Milestone | Status | Scope |
|---|---|---|
| M1–M5 | Completed locally | Django/PostgreSQL/React foundation, evidence/rules schema, team sessions, lobby/practice, round controls and durable Round 1 scoring. |
| M6 | Completed locally | Reviewed Round 1 alternate answers/voids, score/time recalculation and post-final qualification-impact review. |
| M7 | Completed locally for original scope | Participant dashboard and Round 1–4 information/activity pages, release controls and eligibility gates. Round 5 navigation is new M12 work. |
| M8 | Completed locally | Supervised Round 3 tasks, revisioned saves, locked/cutoff submissions, lab judging and reviewed qualification. No website code runner. |
| M9 | Completed locally for original scope | Round 2/4 external scores, faculty/panels, Green Cards, Round 2 → 3 → 4 progression and reviewed roster administration. Round 5 scoring is new M13 work. |
| M10 | Completed locally for original scope | Round 1–4 signed evidence exports, reviewed recovery, retained paper reconciliation and isolated backup/restore rehearsal. Round 5 recovery is new M14 work. |
| M11 | Remaining; partial regression coverage | Integrated local acceptance, now expanded to the complete Round 1 → 2 → 3 → 4 → 5 journey, winner publication, outages/restarts, load and accessibility/device checks. |
| M12 — Round 5 setup and eligibility | Planned; not implemented | Approved format/rules and private content versions, information page/navigation, schedule/contacts and final Round 4 qualifier gates. Gameplay remains offline. |
| M13 — Round 5 scoring and winners | Planned; not implemented | Buzzer/question/reveal evidence, CSV/manual validation and independent commits, stage totals, ranking/ties, corrections, appeals and final winners. |
| M14 — Round 5 recovery and rehearsal | Planned; not implemented | Signed Round 5 source/winner inventories and recovery, host presentation/scorekeeper procedures and retained offline rehearsal evidence. |

Keep existing milestone numbers. Recommended implementation order is **M12 → M13 → M14 → finish M11**. Individual regression checks continue throughout; integrated acceptance closes after Round 5 is implemented. Documentation of the new format is complete, not the new implementation milestones.

## Round 5 scope

The offline buzzer final has five stages: AI-generated image recognition, answer from keywords, word decoding, image abnormalities and progressive image guessing. See [Round 5 requirements](ROUND5_FORMAT.md) for confirmed behavior, planned website responsibilities and unresolved scoring/buzzer decisions.

M1–M10 retain their completed status for the delivered Round 1–4 scope. The new requirements do not imply Round 5 is already supported by those services.

## Existing validation and remaining release work

M10 recorded 201 backend tests passed, one opt-in load test skipped, 100 desktop/mobile browser checks passed, supplementary focused recovery/placeholder checks and an isolated PostgreSQL restore. See [test evidence](TEST_EVIDENCE.md). Those results do not certify Round 5 or the complete five-round event.

Actual tasks/images/answer keys, faculty/hosts/consent, rosters, schedules, venue/network/buzzer procedures, appeal policies and scoring decisions remain organizer inputs. Existing hidden faculty drafts and the [organizer data template](templates/ORGANIZER_DATA.md) provide placeholders. Hosting/TLS, deployed capacity, actual devices/campus checks and physical rehearsal remain separate release gates.
