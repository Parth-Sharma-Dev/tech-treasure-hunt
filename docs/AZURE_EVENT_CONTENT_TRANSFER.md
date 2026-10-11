# Bulk transfer of initial event drafts to Azure

The application ZIP contains code, not local database records. Use the private
`transfer_event_drafts` package to copy the initial prepared real event drafts
without replacing production accounts, MFA devices, team credentials, roster,
demo data or results. The import is transactional and has a dry-run option.

## Prepared package

The private package `.local/deploy/event-content-20261011.zip` contains:

- Five real DRAFT rounds and their existing draft settings.
- All 25 mission records: 13 supplied riddles and 12 image placeholders.
- All 168 independent codes with the exact existing keyword assignments.
- Original private source files with SHA-256 validation and the quiz bank.
- Five unpublished faculty drafts.

There are no uploaded mission images, Round 3 coding tasks or Round 5 questions
in the local real drafts yet. The package does not invent those. Imported missions
start unavailable and unverified; faculty remain unpublished. Owner assignments,
approval and verification must be established using production staff accounts.
Round IDs are assigned by the destination database; use the mapping printed by
the importer rather than localhost IDs. Mission tokens/fallback codes are retained,
but printed QR links must use the production website hostname.

The package contains private answers, codes, locations and faculty contacts. Keep
it outside Git/public assets and do not deploy it as the application ZIP.

## 1. Deploy the updated application code

Use the new combined website release ZIP, which includes both the MFA feature and
the transfer command. Follow [website deployment](AZURE_FRONTEND_DEPLOYMENT.md).
Retain the existing working PostgreSQL settings, CA file and signing keys.

Open **App Services → techtreasurehunt → Development Tools → SSH → Go**, change
to the active application directory containing `manage.py`, and activate `antenv`:

```sh
. antenv/bin/activate
python manage.py migrate --noinput
python manage.py migrate --check
python manage.py help transfer_event_drafts
mkdir -p /home/site/private-transfer
chmod 700 /home/site/private-transfer
```

If MFA is not enrolled yet, follow [staff MFA activation](STAFF_MFA.md).
Take a private production database backup before importing. This content transfer
does not itself take a backup or undo mock gameplay afterward.

## 2. Upload the private data package

In Azure Portal, open **Cloud Shell → Bash**. Use **Manage files → Upload** and
select `event-content-20261011.zip` from the local `.local/deploy` directory.
From the directory where it was uploaded, run:

```sh
az webapp deploy \
  --resource-group tth-event-rg \
  --name techtreasurehunt \
  --src-path event-content-20261011.zip \
  --type static \
  --target-path /home/site/private-transfer/event-content-20261011.zip \
  --clean false \
  --restart false \
  --track-status false \
  --ignore-stack true
```

Use `--type static` exactly: it transfers the ZIP as a file to a private path,
instead of extracting it into the website. This follows
[Azure CLI's file deployment and absolute target-path options](https://learn.microsoft.com/en-us/cli/azure/webapp?view=azure-cli-latest#az-webapp-deploy).

## 3. Dry-run and import in App Service SSH

Return to the App Service SSH terminal with the application virtual environment
active. Replace `YOUR_CONTENT_ADMIN_USERNAME` with the actual Django staff username
that has `competition.prepare_content`; do not use the PostgreSQL login name.

```sh
python manage.py transfer_event_drafts \
  --import \
  --file /home/site/private-transfer/event-content-20261011.zip \
  --actor YOUR_CONTENT_ADMIN_USERNAME \
  --dry-run
```

Expected: **Dry-run passed (no records saved)** with five destination round IDs,
25 missions, 168 codes and five faculty drafts. Dry-run IDs are provisional;
PostgreSQL sequences can advance even when records roll back.

If it succeeds, run the same command without `--dry-run`:

```sh
python manage.py transfer_event_drafts \
  --import \
  --file /home/site/private-transfer/event-content-20261011.zip \
  --actor YOUR_CONTENT_ADMIN_USERNAME
```

Expected: **Imported**, with the final round ID mapping and the same counts.
An error rolls back all destination content writes. The command refuses existing
real content, configured drafts and released rounds; repeated successful imports
are rejected rather than duplicating records. Empty draft shells created using the
same titles are accepted. Do not delete conflicting records to force an import.

## 4. Verify and prepare play

Refresh `/admin/competition/round/`, `/admin/competition/mission/` and
`/admin/competition/huntcode/`. Confirm five real drafts, 25 missions and 168 codes,
and verify your previously created roster and staff accounts remain present.

These records belong to **Real contest**. Teams created under **Local demo** are
in a different cohort and cannot enter these real rounds. Keep cohort selection
consistent before approving or releasing any round.

Configure real owners, timings, advancement/short-roster policy, capacity and the
other required rules. Upload remaining Round 1 images, prepare coding tasks and
Round 5 questions, and complete independent verification/approval. Imported draft
records alone are not READY. Take the clean pre-rehearsal backup after preparation.

Retain the private package locally. After import and verification, remove the
temporary remote package and the Cloud Shell upload through your normal private
file cleanup procedure.

## Export again if local draft content changes

From the repository root on your machine, choose a new filename:

```powershell
.venv/Scripts/python backend/manage.py transfer_event_drafts --export --file .local/deploy/event-content-NEW.zip --actor DEMO-content
```

This initial-draft tool deliberately refuses uploaded image files, legacy
mission-bound answer hashes, prepared coding/buzzer tasks, round information and
faculty-panel assignments; those need a separate content migration. Existing
files are never overwritten. It is not a general synchronization or reset tool.
