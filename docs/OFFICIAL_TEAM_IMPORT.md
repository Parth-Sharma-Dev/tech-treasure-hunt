# Import the 110 official teams into the original Azure database

The organizer supplied `Le_Bhai.csv` and confirmed **four members in all teams**.
It has exactly 110 distinct valid team IDs, leader names, leader emails and supplied
passwords. The private transfer copy is `.local/deploy/teams-110-private.csv`.
Names/emails/passwords are not committed or embedded in the application ZIP.

The actual file was imported on the isolated PostgreSQL test database using the
real Django password hasher. All 110 accounts passed password read-back checks,
with member_count 4, ACTIVE status and is_demo False. This does **not** mean Azure
has been populated: the operator must run the command on the original database.

## 1. Check the target and deploy the new website code

Return App Service to the recorded **original** POSTGRES_HOST and check health.
Take a private database backup. Keep all real rounds DRAFT during roster import;
the command refuses any released real round and never resets states.

Deploy the latest combined website ZIP using the existing deployment procedure.
It includes `import_team_credentials`, the final R1/R2 settings helper and private
image-storage check. Retain existing signing keys, CA path and storage settings.
Wait for Oryx build/startup and a healthy `/api/health` before proceeding.

In App Service SSH, change to the active directory containing `manage.py`, activate
`antenv`, and verify the connection without showing credentials:

```sh
. antenv/bin/activate
python manage.py shell -c "from django.db import connection; print(connection.settings_dict['HOST'], connection.settings_dict['NAME'])"
python manage.py migrate --check
python manage.py help import_team_credentials
mkdir -p /home/site/private-transfer
chmod 700 /home/site/private-transfer
```

Check the hostname is the original database, not `tth-mock-20261011`. If the original
has no real rounds/content, use [private event-content import](AZURE_EVENT_CONTENT_TRANSFER.md)
first or before configuring final rules; it preserves the roster and accounts.

## 2. Transfer the private credential file

In Azure Cloud Shell Bash, use **Manage files → Upload** to upload
`teams-110-private.csv` from `.local/deploy`. Transfer it as a private file:

```sh
az webapp deploy \
  --name techtreasurehunt \
  --resource-group tth-event-rg \
  --src-path teams-110-private.csv \
  --type static \
  --target-path /home/site/private-transfer/teams-110-private.csv \
  --clean false \
  --restart false \
  --ignore-stack true
```

This is data, not the website ZIP. The destination is outside the public code/static
directories. Do not place it in wwwroot/static, React assets or a public Blob.

## 3. Validate, review and import

Back in App Service SSH with the application environment active:

```sh
python manage.py import_team_credentials \
  --csv /home/site/private-transfer/teams-110-private.csv \
  --actor parth \
  --verifier verifier \
  --member-count 4 \
  --expected-count 110 \
  --dry-run
```

Expected: `Dry-run passed; no records saved: 110 real teams, leader emails and
Django-hashed passwords.` Hashing/read-back for all accounts takes a few minutes;
wait for the final message. Dry-run rolls back all account/roster/audit writes.

Check the official file with the verifier, then perform the bulk write:

```sh
python manage.py import_team_credentials \
  --csv /home/site/private-transfer/teams-110-private.csv \
  --actor parth \
  --verifier verifier \
  --member-count 4 \
  --expected-count 110 \
  --review-confirmed
```

Expected: `Imported: 110 real teams, leader emails and Django-hashed passwords.`
This uses the existing two-person roster review services and Django `set_password`.
Each new participant username/team code is the supplied Team ID, with leading zeros
preserved. Display names are `Team <ID>`, leader names are retained on Team and
leader emails on the linked Django User. Participant accounts have no staff/admin
permissions. Supplied passwords are preserved exactly, including punctuation;
plaintext credentials never enter pending roster proposals or audit payloads.

The entire import rolls back on invalid input/conflicting accounts. Existing staff
and demo records are preserved. An additional real team outside the supplied list
blocks import for review instead of silently deleting/disqualifying it. Successful
re-runs reissue credentials and revoke old sessions; run deliberately, not as a
repeated deployment startup step.

## 4. Verify visibility and apply final settings

```sh
python manage.py shell -c "from competition.models import Team; print('Official active four-member teams:', Team.objects.filter(is_demo=False,status='ACTIVE',member_count=4).count())"
python manage.py configure_final_event --actor parth --verifier verifier --dry-run
python manage.py configure_final_event --actor parth --verifier verifier
python manage.py check_mission_storage --actor parth
```

Expect 110 official teams. They sign in using the IDs/passwords in the supplied
CSV, **not** the earlier mock accounts 01/02/03 (those IDs do not overlap this list).
All official teams see the real round cards; R2 participation still requires final
R1 qualification. Use separate test browser profiles and preserve the one-session
rule when checking login.

Complete missing mission images, real QR placements, volunteer ownership and
independent verification before marking READY. See
[final rules/release](FINAL_R1_R2_RELEASE.md) and
[deployed load rehearsal](DEPLOYED_LOAD_TESTING.md).

Keep the original credential list privately offline. After checking the import,
remove only the temporary `/home/site/private-transfer/teams-110-private.csv` and
Cloud Shell copy through your normal private-file cleanup procedure. Keep the
signed database backup/signing keys and private Blob objects for recovery.
