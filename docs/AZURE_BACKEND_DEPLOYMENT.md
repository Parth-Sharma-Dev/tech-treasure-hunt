# Deploy Django first on Azure

This runbook prepares the first deployment to **Linux App Service and PostgreSQL
Flexible Server**, following the 10 October deployment discussion. Resource names,
region, subscription credit and quotas must be selected in Azure. These repository
changes provision no resources. Round 5 content can remain pending in DRAFT; it is
not needed to start Django or run migrations.

The first package exposes `/api/*`, `/admin/` and Django's `/static/` assets. `/`,
`/login`, `/lobby` and `/staff/*` return 404 until React is integrated. Test backend
deployment through the health API and Django admin. React integration should keep
the agreed single browser origin for cookies, CSRF and participant screens.
When ready, follow the [combined frontend deployment](AZURE_FRONTEND_DEPLOYMENT.md)
to add React to this same App Service.

## 1. Prepare the host and database

Use an App Service Linux Python 3.13 runtime, matching the tested local Python
version. Check available runtimes with `az webapp list-runtimes --os linux` before
configuring the app. The discussion's B2 plan, instance count and database size are
provisional until regional quotas, budget and deployed rehearsal are checked.

Configure VNet integration and private DNS so App Service resolves and reaches
PostgreSQL's server FQDN. Keep the database private and require TLS. Use a dedicated
database role rather than the server administrator; give the release role the
schema permissions required for migrations. The live app does not need CREATEDB.
Reviewed recovery into a new database needs a separate authorized recovery role.

Enable HTTPS Only and Always On. Set App Service Health Check to `/api/health`.
This endpoint returns 200 after a database probe or a redacted 503. It is exempt
from Django's HTTP redirect for internal probes; allowed-host checks still apply.
Include the actual App Service hostname used by platform probes in allowed hosts.

During backend setup, restrict public access to organizers and trusted deployment
access. Before participant release, configure Front Door/WAF and block origin
bypass through Private Link or the documented service-tag plus profile-ID approach.
Network and WAF restrictions are Azure configuration; the repository does not
install them. Keep authenticated APIs and evidence out of edge caches.

## 2. Configure app settings and persistent secrets

The settings template is [app-settings.example.json](../infra/azure/app-settings.example.json).
Copy it once to the ignored `.local/azure-app-settings.json`, then replace **every**
`REPLACE_...` value. Prefer App Service Key Vault references backed by managed
identity for Django/answer signing keys and the database password. Verify that
references resolve successfully before starting the app. Do not commit the filled
file or put secrets into CLI command arguments, deployment logs or the ZIP.

| Setting | Required value / meaning |
|---|---|
| `DJANGO_SETTINGS_MODULE` | `config.settings_production`; the startup script rejects other settings. |
| `DJANGO_DEBUG` | `false`. Production never reads the local `.env`. |
| `DJANGO_SECRET_KEY` | Persistent random production key: at least 50 characters, with varied characters. |
| `ANSWER_HMAC_KEY` | Persistent random key of at least 32 characters; preserve the original when moving stored answer hashes. |
| `DJANGO_ALLOWED_HOSTS` | Comma-separated explicit hostnames, including the actual Azure hostname and, later, the public domain. No schemes or wildcards. |
| `DJANGO_CSRF_TRUSTED_ORIGINS` | Comma-separated full HTTPS browser origins; update when the public domain is added. |
| `DJANGO_TRUST_PROXY_SSL_HEADER` | `true` behind App Service's trusted HTTPS proxy. Do not enable for an arbitrary direct Gunicorn server. |
| `POSTGRES_DB`, `POSTGRES_USER`, `POSTGRES_PASSWORD` | Dedicated event database and role credentials. |
| `POSTGRES_HOST`, `POSTGRES_PORT` | Azure server FQDN, port `5432`; private DNS must resolve it from the app. |
| `POSTGRES_SSLROOTCERT` | `system` uses the runtime's system CA trust; alternatively an absolute path to a maintained CA bundle available on every instance. TLS always uses `verify-full`. |
| `WEB_CONCURRENCY` | Initial value `3` synchronous workers per instance; tune through rehearsal. |
| `SCM_DO_BUILD_DURING_DEPLOYMENT` | `true` enables installation of the ZIP's root `requirements.txt`. |
| `DISABLE_COLLECTSTATIC` | `true` skips Oryx's collection; startup collects static files using resolved runtime settings. |

For a new event database, generate the two signing keys separately with a secure
password manager or `secrets.token_urlsafe(64)` and store them privately. Keep them
stable across all instances, restarts and releases. The current local Django key
is a development placeholder and production intentionally refuses it. Retain the
original key privately for verification of old local signed backups/receipts;
changing the key invalidates signatures. Existing accepted evidence must go through
the documented reviewed recovery process rather than an unreviewed key change.

HSTS initially lasts one hour and includes subdomains. Preload is disabled for this
temporary host; `check --deploy` therefore reports the intentional `security.W021`
warning. No checks are silenced. Database requests have a 30-second statement limit,
5-second lock-wait limit and 30-second idle-transaction limit. Validate these limits
against submissions, buzzer bursts and evidence exports during rehearsal. Backup
and recovery client connections inherit the verified TLS policy separately.

## 3. Validate and create the backend package

Run from the repository root with local PostgreSQL available:

```powershell
.venv/Scripts/python backend/manage.py check
.venv/Scripts/ruff check backend tools/package_backend.py
.venv/Scripts/ruff format --check backend tools/package_backend.py
.venv/Scripts/python -m pytest backend
git status --short
$release = git rev-parse --short HEAD
.venv/Scripts/python tools/package_backend.py --output ".local/deploy/backend-$release.zip"
```

Commit and review source changes before packaging a release. The builder reads
tracked Python source under `backend/config` and `backend/competition` from the
working tree plus explicit runtime files. It puts `manage.py` at the ZIP root and
uses pinned production dependencies as root `requirements.txt`. It excludes local
environment files, private event inputs, database dumps, `.git`, tests, development
tools, docs, React and Django's Ruff/pytest `pyproject.toml`. Linux line endings are
normalized. Existing ZIPs are preserved; choose a new filename for a new release.
The builder prints the SHA-256. Keep it and the commit ID with the deployment record.

## 4. Deploy to the prepared App Service

Use the actual names for the already prepared resources. The commands below apply
settings and deploy a package; they do not create hosting resources or push Git.
Run `az login` and select the intended subscription first.

```powershell
$resourceGroup = 'REPLACE_WITH_RESOURCE_GROUP'
$appName = 'REPLACE_WITH_APP_NAME'
az webapp config appsettings set --resource-group $resourceGroup --name $appName --settings "@.local/azure-app-settings.json" --output none
az webapp config set --resource-group $resourceGroup --name $appName --linux-fx-version 'PYTHON|3.13' --always-on true --startup-file 'sh startup.sh' --output none
az webapp update --resource-group $resourceGroup --name $appName --https-only true --output none
az webapp deploy --resource-group $resourceGroup --name $appName --src-path ".local/deploy/backend-$release.zip" --type zip
```

Set the Health Check path separately in the portal. Do not enable
`WEBSITE_RUN_FROM_PACKAGE` for this Python/Oryx workflow. Inspect build and startup
logs for successful dependency installation, checks, collection and Gunicorn
workers. Startup fails on invalid settings or failed collection. Three workers
with one persistent database connection each is an initial connection budget, not
a load guarantee; include additional instances and maintenance connections.

## 5. Apply migrations once and prepare data

Keep participant access closed. Open the App Service application's SSH console
from the portal or `az webapp ssh --resource-group $resourceGroup --name $appName`.
Use the running application's environment and installed Python dependencies.
Oryx serves Python content from `APP_PATH`; do not assume `/home/site/wwwroot` is
the active code directory. In the Linux application shell:

```sh
cd "${APP_PATH:?Locate the active deployed application path}"
python -c "import django; print(django.get_version())"
python manage.py check --deploy
python manage.py migrate --plan
python manage.py migrate --noinput
python manage.py migrate --check
python manage.py createsuperuser
```

If SSH's Python cannot import Django, activate the runtime virtual environment
shown in the startup logs first (commonly `/antenv/bin/activate`). Run migrations
from one release session, once, with a pre-release backup for an existing database.
Startup never migrates, imports content, seeds demos or creates staff automatically.

Code deployment does not transfer the locally prepared event database. For a fresh
database, prepare real staff identities/permissions and privately import reviewed
content and the unchanged **168-code** inventory using the existing management
commands and [event preparation notes](ACTUAL_EVENT_PREPARATION.md). Transfer source
files securely only for that operation. Preserve the answer key if carrying stored
answer hashes. Leave Round 5 unpublished in DRAFT until its actual content arrives.
Do not run demo seed commands in production or treat a fresh schema as event-ready.

For backups/recovery, use a trusted machine or release environment with private
database connectivity and PostgreSQL 18 client tools; those tools are not included
in the ZIP and might not be installed on App Service. Store backups and signed
manifests in private durable storage. Runtime temporary files do not survive all
deployments. Follow [evidence recovery](EVIDENCE_RECOVERY.md), including preservation
of original signing keys and independent review before using restored evidence.

## 6. Verify and proceed to frontend integration

Verify `/api/health` returns 200 through the intended HTTPS path. Check `/admin/`
login and its CSS, CSRF rejection of invalid writes, secure cookies, HTTP redirects,
no-store API responses and request IDs. Confirm health becomes 503 for a database
failure in an isolated rehearsal, and that two app instances share sessions and
unchanged signing secrets. Django `/` returning 404 is expected in this phase.

On a failed release, keep play closed and redeploy the recorded previous ZIP if
its code is compatible with the database schema. A code rollback does not undo
migrations or restore evidence; use reviewed recovery for database incidents.

Before opening play, finish single-origin React integration, staff access/MFA,
Front Door origin restrictions/WAF tuning, alerts/budget checks, and deployed
double-capacity/shared-IP/recovery rehearsal. The old opt-in local load runner is
not a valid 140-team capacity certificate. These remain deployment/release work,
not claims established by the repository's passing functional tests.

Reference behavior was checked against [App Service Python configuration](https://learn.microsoft.com/en-us/azure/app-service/configure-language-python),
[Django deployment on App Service](https://learn.microsoft.com/en-us/azure/app-service/tutorial-python-postgresql-app-django),
[Azure PostgreSQL TLS](https://learn.microsoft.com/en-us/azure/postgresql/security/security-tls)
and [WhiteNoise's Django configuration](https://whitenoise.readthedocs.io/en/stable/django.html).
