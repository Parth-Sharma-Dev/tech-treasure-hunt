# Reviewed Round 2 absences

The organizer confirmed these nine R1 qualifiers did not attend Round 2:
TH0001, TH0002, TH0003, TH0005, TH0008, TH0011, TH0033, TH0041, TH0108.
The committed Wayground report contains the other 41 participant rows.

Deploy the absence-support release before running the commands. No database
migration is required. Retain the genuine workbook and an attendance record
independently reviewed by the verifier; this document records the organizer's
instruction and does not itself prove attendance.

The new source batch stores explicit absences, not invented quiz answers or
answering durations. Its zero numeric value is an absence bookkeeping value,
not a raw Wayground score. Reviewed absentees are excluded from R2 ranking and
qualification. The existing 41 score revisions, R1 final qualifiers, passwords
and roster status are preserved. A participant score cannot be replaced by an
absence through this command. Corrections for misidentified attendance require
genuine reviewed participant evidence, not casual database edits.

## Prepare in App Service SSH

Use the newly deployed active directory with `antenv` activated. Confirm the
original database first, then prepare the batch as the content operator:

```bash
python manage.py shell -c "from django.db import connection; print(connection.settings_dict['HOST'], connection.settings_dict['NAME'])"
python manage.py record_round2_absences \
  --round-id 7 \
  --actor parth \
  --teams TH0001 TH0002 TH0003 TH0005 TH0008 TH0011 TH0033 TH0041 TH0108 \
  --reason "Organizer confirms these nine qualified teams did not attend Round 2." \
  --attendance-reference "Organizer attendance confirmation; independently checked by verifier"
```

This creates a preview batch, not committed results. Save the printed `batch_id`.
If any errors are printed, do not commit; resolve the mismatch with retained
attendance evidence. The command checks the frozen advancement count is 20.

## Independent verification

The actual `verifier` must check the attendance record and the nine codes. Only
after that review, run the command below using the printed ID instead of `123`:

```bash
python manage.py record_round2_absences \
  --round-id 7 \
  --actor verifier \
  --batch-id 123 \
  --review-confirmed \
  --reason "Independently verified all nine teams were absent from Round 2."
```

The same maker cannot commit its own batch. Recommitting an already committed
batch does not create duplicate score revisions. Actor names in SSH are audit
identities; console access alone is not evidence that the human verifier reviewed
the attendance record. Do not claim that review before it happened.

## Publish

Refresh `/staff/results`, select R2 ID 7 and inspect the preview. There should
be 41 eligible scored participants, nine reviewed absentees and no missing-score
evidence gaps. Propose/independently publish PROVISIONAL, allow five minutes for
appeals, resolve material incidents and any cutoff tie, then independently
publish the final top 20. The command does not publish results or bypass appeals.
