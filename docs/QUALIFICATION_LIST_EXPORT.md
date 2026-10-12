Copy `tools/export_qualification_lists.py` to `/tmp/export_qualification_lists.py`
in the production App Service SSH session. This standalone script uses the deployed
models and environment; no application deployment or migration is needed.

From the active application directory (where `manage.py` is), run:

```sh
cd "${APP_PATH:?Locate the active deployed application path}"
python manage.py shell --verbosity 0 -c "import runpy; runpy.run_path('/tmp/export_qualification_lists.py', run_name='__main__')" > /tmp/qualification-lists.json
cat /tmp/qualification-lists.json
```

Use the running application's Python environment, as described in
[the deployment runbook](AZURE_BACKEND_DEPLOYMENT.md#5-apply-migrations-once-and-prepare-data).
The JSON contains four arrays of team codes and names:

- `round_1_disqualified`: teams in final Round 1 standings that did not advance.
- `round_2_qualified`: **45** Round 1 qualifiers, reduced from 50 if necessary.
- `round_2_disqualified`: those 45 entrants minus the final Round 2 qualifiers,
  including absent teams.
- `round_3_qualified`: the published Round 2 qualifiers.

Here “disqualified” means eliminated at that round's cutoff, rather than only teams
with the disciplinary `DISQUALIFIED` roster status. These are historical published
advancement lists; subsequent withdrawals or roster status changes do not rewrite them.
Demo teams are excluded. The latest real attempts of Round 1 and Round 2 must have
published final results. If Round 1 still has 50 published qualifiers, the export
keeps the first 45 by descending score, ascending last completion active time,
then lexicographical team code. An already published list of 45 is preserved.
The remaining five count as eliminated in Round 1. This is an export-only override;
the database's qualification list is unchanged. If Round 2's final qualifiers
include any of those eliminated five, the script stops and names them for review.
It uses a consistent PostgreSQL read-only transaction and never modifies results.
