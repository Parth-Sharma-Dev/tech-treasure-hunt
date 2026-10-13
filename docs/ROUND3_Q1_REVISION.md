# Round 3 Q1 revision: general code reasoning

The organizer replaced the fixed-output question because participants may run
code in the supervised lab. The new Q1 asks for a general iteration-count formula,
tight time complexity and justification for every positive input size. Running
a few examples is not sufficient. It retains the existing fifteen-mark
code-reading slot, TEXT response, all-or-nothing grading and total of 100 marks.
Other questions and the eleven-qualifier count remain unchanged.

Private payload: `.local/deploy/round3-q1-revision.json`. Participant-only text:
`.local/deploy/round3-q1-participant.md`. The private payload includes the revised
judging rubric; never share it with teams or place it in public assets. Update
any printed participant paper to match the revised Q1.

## Apply to the existing DRAFT without an application deployment

Upload `tools/revise_coding_task.py` and the private JSON to Cloud Shell, then:

```bash
for file in revise_coding_task.py round3-q1-revision.json; do
  az webapp deploy \
    --name techtreasurehunt \
    --resource-group tth-event-rg \
    --src-path "$file" \
    --type static \
    --target-path "/home/site/private-transfer/$file" \
    --clean false --restart false --track-status false --ignore-stack true
done
```

In App Service SSH, from the active directory containing `manage.py`, with
`antenv` activated and the original database selected:

```bash
chmod 600 /home/site/private-transfer/round3-q1-revision.json
TTH_CODING_DRY_RUN=1 python manage.py shell -c "import runpy; runpy.run_path('/home/site/private-transfer/revise_coding_task.py', run_name='__main__')"
TTH_CODING_DRY_RUN=0 python manage.py shell -c "import runpy; runpy.run_path('/home/site/private-transfer/revise_coding_task.py', run_name='__main__')"
```

The first command validates and rolls back; the second applies. This requires
the original Q1 to have been imported already and the latest real R3 to remain
DRAFT. A checksum guard refuses to overwrite a different organizer edit. It
does not reset READY or started rounds. Retrying an applied revision is harmless.

The update changes Q1 prompt, private rubric and version, stores private revision
evidence and audits the action. It preserves points, category, languages and all
other tasks. It clears Q1 verification and stale round rule approval.

After applying, check Q1 in Coding tasks admin. Have the actual `verifier`
independently verify the revised question/rubric and reapprove current round
rules before marking READY. The original confidential Word paper stays retained
as historical source evidence; the reviewed revision supersedes its original Q1.
