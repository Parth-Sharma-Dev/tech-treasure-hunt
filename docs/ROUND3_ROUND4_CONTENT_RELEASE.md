# Round 3 and Round 4 content release

Organizer instructions on 12 October supersede the supplied Word paper's
top-ten references: Round 3 admits the final R2 qualifiers and advances **11**;
Round 4 interviews those eleven and advances up to **five Green Card recipients**.
Round 4 has no fixed question bank, numerical criteria or carried score.
Existing faculty identities remain; participant faculty cards show no portraits.

## Prepared private content

Source: `Tech_Treasure_Hunt_Round_3_Simplified.docx`. The private derived bundle
is `.local/deploy/round3-private-content.json`. It includes the original bytes
and checksum, five participant prompts and separate confidential lab rubrics.
The short-programming task has ten hidden tests, worth three points each. All
ten input lengths and expected sums were checked against the stated problem.
Do not distribute this bundle or the source document's confidential judging pack.
Do not deploy either as public application files.

The document specifies 13 October, 12:00–12:45 PM IST, Python 3.13.13 and C
compiler 15.2.0 using C99 where supported. The importer prepares this schedule
as unpublished information; confirm the actual lab, compiler command, staff,
workstations and timing before publication. Hidden tests remain judge-only.
The website saves code; judges execute it on supervised lab machines.

## Deploy code, then transfer private content

Deploy the new combined website ZIP containing `import_round3_content` and
the eleven-qualifier validation. Keep the current production database, signing
secrets and private storage settings. No new migration is required.

Upload `round3-private-content.json` separately to Cloud Shell. Transfer it into
the private persistent directory using:

```bash
az webapp deploy \
  --name techtreasurehunt \
  --resource-group tth-event-rg \
  --src-path round3-private-content.json \
  --type static \
  --target-path /home/site/private-transfer/round3-private-content.json \
  --clean false \
  --restart false \
  --track-status false \
  --ignore-stack true
```

In the new active App Service SSH directory with `antenv` activated, confirm
the original server/database and protect the transfer file:

```bash
python manage.py shell -c "from django.db import connection; print(connection.settings_dict['HOST'], connection.settings_dict['NAME'])"
chmod 600 /home/site/private-transfer/round3-private-content.json
python manage.py import_round3_content \
  --bundle /home/site/private-transfer/round3-private-content.json \
  --actor parth --verifier verifier --dry-run
```

The dry run rolls back all database records. Serial sequence values may advance.
Both latest real R3 and R4 must remain DRAFT. Existing coding tasks, different
retained papers or published R3 information stop the import; do not delete them
or reset states to bypass the guard. If the dry-run output is correct, apply:

```bash
python manage.py import_round3_content \
  --bundle /home/site/private-transfer/round3-private-content.json \
  --actor parth --verifier verifier
```

The command sets R3 to 45 minutes and eleven qualifiers, imports five unverified
tasks, configures R4 for Green Cards with cut five, preserves faculty identities,
and clears stale draft rule approvals. It does not change R1/R2 results, roster,
passwords, eligibility or faculty publication. R4 retains its current nonzero
duration, otherwise defaults to 60 minutes; verify the intended duration.
All organizers must review the resulting operational policies before approval.

## Human verification and release

1. Check the five tasks in Coding tasks admin. Have `verifier` independently
   verify the actual prompts, languages, starter code, rubrics and hidden tests.
2. Confirm the lab toolchain, judging staff, station labels and participant
   restrictions. Prepare the physical workstation register for twenty entrants.
3. Add the actual venue/help contacts to R3 Round information and independently
   publish it. Questions/answers do not belong in general Round information.
4. Independently approve R3 rules, then mark READY. Content freezes at READY.
5. For R4, retain existing faculty names. If profiles are unpublished, a different
   authorized verifier must review consent and publish them. No photo is needed.
6. Publish the actual R4 venue/schedule/help instructions, approve its Green Card
   rules and mark READY. No predefined questions, weighted marks or compulsory
   panel criteria are required. Exactly eleven eligibility candidates come from
   R3 final results; up to five reviewed recipients advance.
7. Open/start R3 only after R2 FINAL. Assign each team's active browser to its
   supervised workstation through `/staff/coding`. Judge immutable final work,
   independently review scores, publish provisional, resolve ties/appeals and
   finalize eleven before opening R4.
8. After R4 ends, enter the complete Green Card recipient list in `/staff/scores`,
   dry-run and independently commit. Unlisted eligible teams receive no card.
   Publish provisional/final with appeals; do not automatically fill vacant cards.

References: [coding operations](ROUND3_OPERATIONS.md),
[Green Card operations](EXTERNAL_ROUND_OPERATIONS.md).
