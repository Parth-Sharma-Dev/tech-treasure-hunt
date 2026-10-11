# Final Round 1 and 2 release: 110 teams

The organizer confirmed on 11 October: R1 60 minutes, 50 qualifiers; R2 60 minutes,
20 qualifiers; both appeal windows five minutes. Round 2 remains Wayground with
30 questions, exported raw Score and reported answering duration for score ties.
The new release enforces this R2 schedule for new real drafts while preserving
frozen 45-minute/15-qualifier Wayground attempts for historical scoring/recovery.

## Apply the settings to the original database

After switching back, check App Service points to the **original** PostgreSQL
hostname. The mock database retains its rehearsal evidence separately. Deploy
the latest website release because the older code rejects the new R2 schedule.
Keep the working CA path, signing keys and private Blob settings.

Complete the real roster while all real rounds are DRAFT, then run in App Service
SSH from the active application directory with `antenv` active:

```sh
python manage.py configure_final_event --actor parth --verifier verifier --dry-run
python manage.py configure_final_event --actor parth --verifier verifier
```

The helper sets the two latest real drafts to 3,600,000 ms, cuts 50/20, correct
delivery rules, five-minute appeals and production owner IDs. It clears stale
approval and prints remaining readiness blockers. It does not release play,
approve content or create qualification. Released rounds are never reset/edited.

Manual equivalents:

| Field | R1 | R2 |
|---|---|---|
| Delivery | ONLINE_HUNT | EXTERNAL |
| Rules version | event-r1-20261012-v1 | event-r2-20261012-v1 |
| Budget ms | 3600000 | 3600000 |
| Advancement count | 50 | 20 |
| Is demo | Unchecked | Unchecked |
| Rules JSON | [R1 JSON](examples/round1-final-rules.json) | [R2 JSON](examples/round2-final-rules.json) |

The helper resolves `parth` for technical/content/operations/adjudication roles
and the different `verifier` account for verification. The first needs
prepare_content/control_round and the second verify_evidence/publish_results.
Staff need MFA for web workflows. Use actual venue staffing for mission owners.
General movement/accessibility/tool/retention instructions in the JSON are
operational defaults for organizer review; supply and check the actual referenced
route plan, venue information and schedules before independent rule approval.

The registration cap is 110 teams; peak browser planning is 112 (110 team browsers
plus the two staff browsers). These are planning values, not a capacity certificate.

## Roster and visibility

The supplied initial CSV has 110 Team ID/Password rows. Full registration details
are pending because teams contain a mix of three/four members. Preserve leading
zeros, use supplied membership counts and set every official team `is_demo=False`.
Use Django's password hashing API; never assign a plaintext string to `User.password`.
Credentials and source files remain private, outside Git/public site assets.

All active real-cohort teams see the real round cards on the dashboard. Round 1
is accessible to all active entrants. Round 2 activity remains restricted to the
50 independently finalized R1 qualifiers; making a card visible does not grant
eligibility. R2 final publication advances 20. Extra mock teams must not inflate
the official roster or consume the 110-team cap.

## The 25 mission records are not yet event-ready

The supplied local drafts contain 13 riddles and 12 empty image-clue records,
plus 168 fixed independent code/keyword pairs. All have missing volunteer owners,
QR placement and verification; imported missions are unavailable. Production
may have further edits, which must be checked there rather than inferred locally.

For each mission, while R1 is DRAFT:

1. Preserve its clue/navigation token and private destination. Put the actual QR
   placement in QR location and select the responsible active staff volunteer.
2. For MISSION-14 through MISSION-25, upload the organizer's actual image and
   neutral alternative text. Do not put a destination answer or collectible code
   in participant hint/symbol/alternative text.
3. Mark Available only after the clue is complete. For independent-code missions,
   leave Answer and Keyword empty: those belong to the separate HuntCode pool.
4. The different verifier checks the clue and, for images, its private preview,
   then attests to independent end-to-end verification. Content edits invalidate
   verification. Repeat for all 25, then approve the current rules and mark READY.

Actual missing images, physical placements and human verification cannot be
fabricated from draft placeholders. All 25 intended clues must be completed before
the final rules' expected_mission_count 25 will pass readiness.

Codes are exclusive between teams. With 168 codes and 110 entrants, not every
team can claim three codes (that would require 330 distinct codes). This retains
the previously approved scarce independent-code competition, not shared answers.

## Verify image upload on Azure

In App Service SSH after deploying the new release:

```sh
python manage.py check_mission_storage --actor parth
```

This writes/reads a new disposable PNG, checks its bytes and attempts to remove it;
no mission record changes. Success verifies the runtime's storage write/read path,
not every possible upload or later network outage. Check any cleanup warning.
Then perform one actual admin upload, private preview and participant-open/download
rehearsal before publishing all image clues.

Upload support exists for **any competitive Round 1 mission**, including replacing
a text riddle with an image, when the round is DRAFT and the content staff sets
clue type IMAGE. Use a still JPEG/PNG/WebP, at most 5 MiB, at most 4096 pixels per
side and eight megapixels. Its normalized PNG must fit 2 MiB; reduce dimensions if
needed. Alternative text is required. A READY/released attempt freezes content
and cannot accept new image uploads in place.

Azure needs the existing private container, managed identity with Storage Blob
Data Contributor, correct AZURE_MISSION_ACCOUNT_NAME/AZURE_MISSION_CONTAINER and
network access. See [image storage preparation](ROUND1_IMAGE_CONTENT.md).

## Release and score

Once roster/content are complete, verifier independently approves rules and
content; parth marks READY. Publish participant information separately with the
actual venues, timetable and help contacts. Keep clues/answers out of general
information. Before releasing, take the clean database backup and retain matching
private Blob objects/signing keys.

R1: open lobby/start, run 60 active minutes, end, propose/independently publish
provisional results, resolve incidents and wait the full five-minute appeal window,
then independently publish final 50 qualifiers. Exact cutoff ties need the
declared supervised reserve procedure; display order is not a tie-break.

R2: open/start only after R1 FINAL. Run Wayground under the approved supervision,
end the website attempt and import the genuine original workbook. Map every row
to a qualified team or explicitly exclude it, ensure every entrant has coverage,
dry-run, and have verifier independently commit. Publish provisional, wait five
minutes and resolve blockers, then independently publish final 20 qualifiers.
Never use the synthetic mock workbook for official results.

Complete [deployed load testing](DEPLOYED_LOAD_TESTING.md) on a new isolated copy;
functional/mock tests alone do not demonstrate deployed capacity.
