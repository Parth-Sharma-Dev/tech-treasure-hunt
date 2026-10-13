# Round 3: bulk import of the proposed grades

All twenty teams were assessed in `.local/round3-grading/round3-grading-review.json`.
The corresponding CSV lists all twenty ranks and individual question marks.
Q1 uses the organizer's revised requirement: formula and general explanation,
without time complexity. The frozen rubric's old complexity requirement was
ignored under that explicit instruction. Qualitative judgments and execution
evidence remain subject to real independent verification.

No application deployment or migration is needed. Upload these three private
files to Cloud Shell:

- `tools/import_coding_grades.py`
- `.local/round3-grading/round3-grading-review.json`
- `.local/round3-grading/execution-results.json`

Transfer them into persistent private storage:

```bash
for file in import_coding_grades.py round3-grading-review.json execution-results.json; do
  az webapp deploy \
    --name techtreasurehunt --resource-group tth-event-rg \
    --src-path "$file" --type static \
    --target-path "/home/site/private-transfer/$file" \
    --clean false --restart false --track-status false --ignore-stack true
done
```

In App Service SSH, from the active directory with `antenv` activated, confirm
the original server/database. Protect the files:

```bash
python manage.py shell -c "from django.db import connection; print(connection.settings_dict['HOST'], connection.settings_dict['NAME'])"
chmod 600 /home/site/private-transfer/round3-grading-review.json /home/site/private-transfer/execution-results.json
```

## parth: propose all twenty lab judgments

```bash
TTH_GRADING_OPERATION=propose TTH_GRADING_ACTOR=parth python manage.py shell -c "import runpy; runpy.run_path('/home/site/private-transfer/import_coding_grades.py', run_name='__main__')"
```

Check the output and grading reasons against saved submissions. This creates
pending proposals only. A failure rolls back the whole batch. The script requires
the ended real round, a frozen cut of eleven, exact final timestamps/source-bound
grades and complete coverage of all saved final submissions. It refuses to
automatically overwrite unrelated existing reviewed judgments. Retry the same
unchanged report safely if the console outcome was uncertain.

## verifier: independently review and approve

The actual verifier must inspect the private grading report, saved source,
execution evidence, Q1 instruction and final-time evidence. Only after that
review, run:

```bash
TTH_GRADING_OPERATION=approve TTH_GRADING_ACTOR=verifier TTH_GRADING_REVIEW_CONFIRMED=1 python manage.py shell -c "import runpy; runpy.run_path('/home/site/private-transfer/import_coding_grades.py', run_name='__main__')"
```

This independently commits grades through the ordinary judgment service. Actor
names are audit identities; console access alone does not prove that the human
review happened. Do not set confirmation before actual verification. A maker
cannot approve its own judgment. Repeating an unchanged approved batch does not
award duplicate marks.

## Publish normally

Refresh `/staff/results`, select Round 3 ID 8 and compare its ranking with the
private CSV. Propose provisional results as parth; independently publish as
verifier. Resolve appeals/material gaps and wait the approved five-minute window,
then independently publish FINAL with eleven qualifiers. The import script does
not publish results, alter prior-round qualification or bypass appeal requirements.
