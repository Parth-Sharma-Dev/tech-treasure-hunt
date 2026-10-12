# Round 2: reviewed correction to the exported workbook ranking

The organizer explicitly requested the workbook's ranking after reviewing the
difference from the originally configured raw-score/time ranking. The correction
uses the retained `Rank` column exactly, not an inferred accuracy tie-break.
Raw scores, answering durations, original workbook bytes and historical revisions
remain retained. Reviewed absences remain ineligible for R2 qualification.

This is a reviewed ranking decision after play, not a silent edit to the frozen
rules. It is stored in a new source batch and independent score revisions, and
the public explanation identifies the workbook ranking. Notify participants of
the decision when publishing corrected provisional results. The cut remains 20.

Deploy the new release. No migration is required. Do not change databases or
re-upload the workbook: the command reads the existing committed report and
preserves its reviewed team mappings. It refuses FINALIZED rounds; do not undo
finalization or edit old snapshots to force a different outcome.

## Prepare the correction

In the newly deployed App Service SSH application directory with `antenv` active:

```bash
python manage.py use_wayground_workbook_ranking \
  --round-id 7 \
  --actor parth \
  --prepare \
  --reason "Organizer requests Round 2 qualification to follow the exported Wayground Rank column." \
  --decision-reference "Organizer ranking decision: use original workbook Rank; final cut 20"
```

Review the preview's team codes, `workbook_rank`, scores and times against the
retained file. Record the printed `batch_id`. Preparation does not alter effective
scores or publish results. Every exported rank must be a distinct positive integer.
The command expects all participant scores from one committed report batch.

## Independent commit

Have the actual verifier review both the organizer's decision and the source
workbook/team mappings. Replace `123` with the new batch ID and only then run:

```bash
python manage.py use_wayground_workbook_ranking \
  --round-id 7 \
  --actor verifier \
  --batch-id 123 \
  --review-confirmed \
  --reason "Independently reviewed the workbook ranks, team mappings and organizer ranking decision."
```

The same operator cannot approve their own batch. This appends score revisions;
numeric scores remain the same, but rankings and top-20 qualification follow the
recorded workbook ranks. Original scores and earlier publications remain history.
If absence evidence is not committed yet, follow [absence intake](ROUND2_ABSENCE_INTAKE.md)
before publication. Do not withdraw the nine absent teams from the global roster.

## Publish the correct results

Refresh `/staff/results`, select R2 ID 7 and compare the order with the workbook.
Propose and independently publish a new PROVISIONAL snapshot. If provisional
results were previously published, the corrected publication restarts the full
five-minute appeal window; the old snapshot remains in history until superseded.
Resolve incidents and appeals, then independently publish the final top 20.
Committing the correction alone does not replace participant-facing publications.

Public notice suggestion:

> Round 2 provisional standings follow the Rank column of the original Wayground
> report, as reviewed by the organizers. Displayed game scores are retained for
> reference. The top 20 advance after the five-minute appeal window and final review.
