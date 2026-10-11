# Staff MFA activation and recovery

This release requires a staff password plus an authenticator-app TOTP code or
one-use recovery code for `/admin/` and every `/api/staff/` endpoint. Existing
password-only sessions cannot use staff endpoints. Team login is unchanged.
Production always enforces MFA; an environment variable cannot disable it.

## Activate on the existing Azure deployment

1. Take a private database backup using the existing backup/recovery procedure.
   Deploy the **new combined website ZIP** following
   [the frontend deployment guide](AZURE_FRONTEND_DEPLOYMENT.md). Keep your
   working Azure environment settings, PostgreSQL CA file path, signing keys,
   private network, and media storage settings.
2. In Azure Portal, open **App Services → techtreasurehunt → Development Tools →
   SSH → Go**. Use the active application directory shown in the startup logs
   (the Oryx-extracted `/tmp/...` directory containing `manage.py` and `antenv`).
   In that directory activate the virtual environment and migrate:

   ```sh
   . antenv/bin/activate
   python manage.py migrate --noinput
   python manage.py migrate --check
   python manage.py check --deploy
   ```

   Migrations include `otp_totp`, `otp_static`, and `competition.0023_staff_mfa`.
   Check each command succeeds before continuing. The earlier intentional
   `security.W021` preload warning does not prevent migration or MFA.
3. For your first existing superuser, issue a private enrollment code from this
   trusted SSH console. Replace both example names with that superuser's actual
   Django username. This is **not** the PostgreSQL administrator username:

   ```sh
   python manage.py issue_staff_mfa_enrollment \
     --username YOUR_DJANGO_SUPERUSER \
     --actor YOUR_DJANGO_SUPERUSER \
     --reason "Supervised initial MFA enrollment"
   ```

   The code expires after 30 minutes and can start enrollment once. Keep it
   private; do not put it in chat, tickets, shared screenshots, or logs.
4. Open `https://YOUR_CURRENT_WEBSITE_HOST/staff-mfa/enroll/`. Use the working
   Azure hostname until the custom domain is live; use `www.techtreasurehunt.in`
   after its DNS/TLS setup is complete. Enter the staff username, password, and
   enrollment code. Scan the displayed QR code using an authenticator app's
   generic TOTP account option, or enter the manual setup key. Keep the phone's
   time automatic. Enter its current six-digit code within five minutes.
5. Save the **ten recovery codes** in private storage. They are shown once.
   Each can replace the authenticator code for one login, with the password
   still required. Finish enrollment before refreshing this page.
6. Enroll every other staff account using a separate issued code. The `--actor`
   must be an active Django superuser; `--username` is the staff account being
   enrolled. Set up a second independent superuser with MFA and private recovery
   codes so a lost phone does not leave you dependent on one person.
7. In a fresh browser/private window, open `/admin/login/`. Enter username,
   password, **Second factor: Authenticator app**, and its current code.
   Verify admin and `/staff/rounds` open. A code already accepted during
   enrollment/login cannot be reused; wait for the next code if needed. Check
   an anonymous browser gets 403 from `/api/staff/rounds` and cannot open admin.
   Test a recovery-code login in another fresh window with **Second factor:
   One-time recovery code**. Confirm that code cannot be used again.

No new secret environment variable or email/SMS service is needed. OTP devices
and recovery codes are stored in your private PostgreSQL database; protect its
access and backups as authentication secrets. Device/key administration is not
exposed in the web admin.

## Day-to-day use

MFA verification lasts at most 12 hours. After expiry, staff must sign in again
with both factors. Staff pages show a sign-in link and retain saved requests;
after returning, use **Retry saved action** or **Retry same action** to resolve
the original outcome. Existing permissions and independent-review requirements
still apply after MFA.

Five staff sign-in attempts per account within five minutes are allowed before
the account temporarily waits. OTP failures also use device throttling and TOTP
replay protection. Do not repeatedly guess codes. Confirm the username,
password, selected factor, and automatic phone time, then wait as instructed.

To replace recovery codes while you still have MFA access, open
`/staff-mfa/recovery/`, confirm your current password, and save the new ten codes.
All older recovery codes immediately stop working. Only a verified staff session
can use this page.

## Lost phone and no remaining recovery code

A **different active superuser** must review the staff member's identity and
authorize a reset through trusted Azure SSH. Replace the example usernames and
record the actual review reason:

```sh
python manage.py reset_staff_mfa \
  --username AFFECTED_STAFF_USERNAME \
  --actor DIFFERENT_SUPERUSER_USERNAME \
  --reason "Identity checked in person by organizer; lost authenticator"
```

This revokes the old devices, codes, and their MFA session access, and outputs a
new private enrollment code. The affected person follows first-time enrollment
again. Reset and enrollment events are recorded in the audit trail without OTP
keys or raw codes. Keep deployment-console access limited to trusted operators.

## Recovery and edge protection

The repository's `restore_competition` workflow clears restored Django sessions,
recovery tokens, and outstanding enrollment invitations, including when restoring
a backup taken before MFA existed. Authenticators remain usable after a fresh
login; replace recovery codes afterward. Follow
[evidence recovery](EVIDENCE_RECOVERY.md) for team sessions and evidence review.
For a manual Azure database restore, the same authentication revocation must be
performed before reopening staff access; the repository cannot automatically
execute its recovery hook for a restore performed outside it.

Front Door/WAF staff restrictions must cover `/staff-mfa/*` as well as `/admin/*`
and `/api/staff/*`. Disable caching for these paths. Avoid capturing passwords,
`otp_token`, `token`, and `invitation` request fields in diagnostics. Complete
the deployed origin restrictions and recovery/capacity rehearsal independently
of this code change.

## Validation

The MFA suite uses real production enforcement and tests password-only denial,
old/expired sessions, OTP replay, one-use recovery codes, CSRF, invitation expiry,
lost-device reset, and restored authentication revocation. An opt-in Chromium
test exercises real Django enrollment, QR loading, TOTP and recovery login.
Legacy gameplay fixtures bypass MFA only inside isolated tests; the extracted
production package is separately checked for mandatory enforcement.

Implementation uses [django-otp's authenticated admin and transactional device
verification](https://django-otp-official.readthedocs.io/en/stable/auth.html).
Azure's runtime environment and startup behavior are described in
[App Service Python configuration](https://learn.microsoft.com/en-us/azure/app-service/configure-language-python).
