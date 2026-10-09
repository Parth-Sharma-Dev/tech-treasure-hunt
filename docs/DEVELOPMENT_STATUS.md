# Development milestone status

Updated 9 October 2026 after M14. Round 5 now has native buzzer/host evidence, reviewed cumulative scoring, one event winner and signed native recovery. Actual event inputs, physical rehearsal and production release remain separate.

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
| M13 — Round 5 scoring and winners | Completed locally | Five questions/stage, two marks/correct, zero penalties; host completion records, buzzer-linked source ledgers, independent review/corrections, final Round 1–4 carry-over, last-correct completion ranking and one event winner. |
| M14 — Round 5 recovery and rehearsal | Completed locally; physical rehearsal pending | Signed native question/window/press/host/source/winner inventories, exact carried-result dependencies, independently reviewed recovery and synthetic restore drill; host/admin/scorekeeper run sheet and actual-phone evidence template. |

Keep existing milestone numbers. **M1–M10 and M12–M14 are complete locally.** Next: **finish M11**. Integrated acceptance still requires the complete competitive chain, broader outages/load and actual event rehearsal.

Use the [M11 manual acceptance walkthrough](M11_ACCEPTANCE_TESTING.md) for the complete operator journey, expected scores/gates, interruption/recovery branches and pending sign-off record. Section 25 of the private admin/round operations guide contains the same checklist. Preparing the guide does not mark M11 complete.

A [fresh professor demo journey](PROFESSOR_DEMO.md) was prepared on 10 October after the guided rehearsal: R1 attempt 3 and R2–5 attempt 2, all DRAFT with 60-minute clocks and one-minute demo appeals. Earlier final results/press evidence remain preserved; copied content awaits independent verification and release. The interrupted first R5 run and actual content/device/load work keep M11 pending.

## Round 5 scope

The final has five stages: AI-generated image recognition, answer from keywords, word decoding, image abnormalities and progressive image guessing. Teams press the website buzzer; the admin sees server press times and closes the window to confirm the earliest valid team's offline answering opportunity. No client-time or latency compensation is applied. See [Round 5 operations](ROUND5_OPERATIONS.md) and [remaining inputs](ROUND5_FORMAT.md).

M1–M10 retain their completed status for the delivered Round 1–4 scope. M12–M14 supply Round 5's native buzzer, scoring/award and signed recovery extensions.

## Existing validation and remaining release work

M10 recorded 201 backend tests passed, one opt-in load test skipped, 100 desktop/mobile browser checks passed, supplementary focused recovery/placeholder checks and an isolated PostgreSQL restore. See [test evidence](TEST_EVIDENCE.md). Those results do not certify Round 5 or the complete five-round event.

M12 recorded **213 passed / 1 skipped** in the backend suite and **112 passed** in the browser suite. Its fifth actual HTTP/PostgreSQL journey covers lost-response recovery and window isolation; concurrency tests preserve received-time order through reversed commits. M13 adds final scoring/awards below; M14 extends signed native recovery.

M13's final clean run passed **230 backend tests / 1 skipped** and **122 desktop/mobile browser checks**. A sixth actual browser/database journey covers the last live answer, independent source commit, provisional publication and final event award. A synthetic fixture advances only its publication clock; the application cannot skip appeals. See [scoring operation](ROUND5_SCORING.md) and [test evidence](TEST_EVIDENCE.md).

M14 passed **243 backend tests / 1 skipped** and **124 desktop/mobile browser checks**. Its isolated 25-question restore recovers exact native evidence, cumulative standings and one historical event winner, with revoked access and closed windows. Signed v3 dependencies reject changed or missing prior finals, conflicting original times and inconsistent awards; an older ENDED database cannot bypass final publication permission. Build/lint/format/system/migration checks passed. See [recovery operations](EVIDENCE_RECOVERY.md) and the [host/scorekeeper run sheet](ROUND5_REHEARSAL.md). The [actual-device rehearsal record](templates/ROUND5_REHEARSAL_RECORD.md) remains pending, with explicit placeholders.

Actual tasks/images/answer keys, faculty/hosts/consent, rosters, schedules, venue/network/buzzer procedures, appeal policies and scoring decisions remain organizer inputs. Existing hidden faculty drafts and the [organizer data template](templates/ORGANIZER_DATA.md) provide placeholders. Hosting/TLS, deployed capacity, actual devices/campus checks and physical rehearsal remain separate release gates.
