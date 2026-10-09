# Round 1–4 evidence recovery

Updated 9 October 2026. M10 extends the existing Round 1 recovery and paper tools to coding, external scores, faculty and roster evidence. Use `/staff/results`, select the exact round attempt, and open **Evidence exports and recovery**. Paper activation and receipt verification remain Round 1 operations.

The [Round 5 website buzzer](ROUND5_OPERATIONS.md) is implemented in M12. M14 still extends native signed inventories/reconciliation to its window/press timestamps/order/admin controls and future linked scores/winners. Whole-database backups include these tables, but current signed per-round reconciliation covers Rounds 1–4. Recovery must not reopen old windows or replay presses into a new question. See [milestone status](DEVELOPMENT_STATUS.md).

## Capture and retain

Download a signed round checkpoint after ENDED, PROVISIONAL or FINALIZED. A v2 checkpoint includes:

- Round configuration, frozen rules/panels/slots, clock intervals, incidents, results and relevant audit events.
- Round 1 decisions, receipts, corrections, completions and reconciled paper slips.
- Round 3 private task/rubric versions, every acknowledged source revision, final/cutoff/no-submission records, workstation evidence, judgment proposals and reviewed verdicts.
- Round 2/4 original import batches, appended score revisions and reviewed Round 2 question voids.
- The cohort's faculty drafts/approved snapshots, roster proposals/review audits and team identity/status inventory.
- Session identities and timestamps, with no session cookies or password hashes.

Checkpoints are signed, **not encrypted**. They contain private tests, sources, original faculty marks and personal information. Retain them privately with authorized reviewers and keep signing secrets separately. Participant endpoints do not expose this evidence.

Per-type JSON or CSV exports contain at most 200 records by default, at most 500. JSON pages contain signed manifests and `next_cursor`; follow the cursor until null. CSV cells are spreadsheet-safe and response headers contain the signed inventory digest and next cursor. Restart pagination when evidence changes. Pages support investigation; upload a complete signed checkpoint for reconciliation.

Browser checkpoints retain the existing 10,000-record/8 MB signed-content limits. Local capture preserves existing files:

```powershell
.venv/Scripts/python backend/manage.py export_round_evidence --round <DATABASE_ROUND_ID> --actor <AUTHORIZED_STAFF_USERNAME> --output .local/round-checkpoint.json
.venv/Scripts/python backend/manage.py backup_competition --output .local/competition-checkpoint.dump
.venv/Scripts/python backend/manage.py restore_competition --backup .local/competition-checkpoint.dump --database tth_recovery_rehearsal_new --actor <AUTHORIZED_CONTROLLER_USERNAME>
```

Replace bracketed arguments with real IDs/usernames. The restore target must be a new `tth_recovery_*` database; the source and existing targets are preserved. Follow the separate-port preview instructions in [Round 1 operations](ROUND1_OPERATIONS.md). Baseline restore incidents remain open until independently reviewed.

## Reconcile on the separate recovery database

1. Stop and persist **all LIVE/FROZEN rounds in the cohort**. Shared team sessions will be revoked. Use retained ended checkpoints; live-clock recovery needs supervised coverage review.
2. Verify the restored accounts/team identities against the signed inventory. Missing, additional or changed identities require separate supervised account/roster recovery. Checkpoints do not create participant accounts or restore passwords.
3. Reconcile earlier-round qualification evidence first. A later-round checkpoint does not invent a missing earlier final snapshot.
4. Select the exact attempt, upload its signed checkpoint and supply real recovery evidence references. Review missing, changed, additional and team-status differences before proposing reconciliation.
5. A different authorized verifier checks coverage and approves. Finalized results additionally require publication permission. Repeating the same request UUID returns its original result.
6. Recovery appends exact missing signed records and restores permitted Round 1 projections/clock state. Changed original sources, faculty records, coding assignments or score batches require investigation; they are not overwritten. Newer unbacked evidence also blocks reconciliation.
7. Missing historical workstation sessions become revoked tombstones with fresh unusable identifiers. All cohort sessions are revoked again at approval, including any created during review. Existing withdrawal/disqualification restrictions survive; stricter checkpoint restrictions are reapplied.
8. The native scoring strategy checks recovered evidence. Missing final/no-submission records, source hashes, supervised judging or verified external sources block successful reconciliation and leave the material incident open. Database sequences are advanced so restored IDs cannot cause duplicate insertion.
9. Independently resolve remaining baseline incidents and any outage interval beyond the retained checkpoint before finalization/progression. A checkpoint cannot prove that no later records were lost.

Original signed v1 Round 1 checkpoints remain supported. They cannot certify later-round evidence; use v2 checkpoints for Rounds 2–4.

## Local placeholder data

```powershell
.venv/Scripts/python backend/manage.py seed_organizer_placeholders --actor DEMO-content
```

This DEBUG-only command creates six **unpublished demo faculty drafts** labeled `PLACEHOLDER — Panel A/B faculty 1/2/3`, plus missing information drafts for the latest DRAFT demo rounds. Existing information, released rounds and real-cohort records are preserved. Repeated runs preserve existing drafts and organizer edits.

Edit faculty records at `/admin/competition/facultyprofile/` and information at `/admin/competition/roundinformation/`. Supply actual names, approved roles/location/contact, consent references and optional HTTPS portraits. Blank portraits use the existing initials placeholder after publication. Faculty drafts start hidden; consent is blank, dates remain unset and no panel/team assignments are fabricated. Set visibility and obtain independent publication review only after actual details are approved.

Use the [organizer data checklist](templates/ORGANIZER_DATA.md) for remaining inputs. Placeholder text must never stand in for score, consent, qualification or outage-coverage evidence.
