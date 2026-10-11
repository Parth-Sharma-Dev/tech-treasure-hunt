# Add React to the Azure deployment

The agreed deployment serves compiled React, Django API and Django admin from the
same Linux App Service behind Front Door. This keeps the existing relative API
URLs, same-origin sessions and CSRF workflow. Node is used to build the frontend;
the deployed app continues to run Python/Gunicorn. A separate frontend host is not
part of this package or the recorded architecture.

Complete the [backend setup](AZURE_BACKEND_DEPLOYMENT.md), including PostgreSQL,
production secrets and network configuration first. Then deploy a **combined
website ZIP** to that same app. This replaces the application's code/assets;
PostgreSQL and its content remain separate. Do not upload `frontend/dist` alone to
the Python app, because a deployment must also contain the Django runtime files.

## Build, validate and package

Use Node 24 and the repository's Python environment. From the repository root:

```powershell
Push-Location frontend
npm.cmd ci
npm.cmd run build
npm.cmd run test:e2e -- --workers=2
Pop-Location
.venv/Scripts/python backend/manage.py check
.venv/Scripts/ruff check backend
.venv/Scripts/ruff check --config backend/pyproject.toml tools/package_backend.py
.venv/Scripts/python -m pytest backend/tests/test_deployment.py backend/tests/test_foundation.py
git status --short
$release = git rev-parse --short HEAD
.venv/Scripts/python tools/package_backend.py --frontend-dist frontend/dist --output ".local/deploy/website-$release.zip"
```

Review and commit source changes before packaging; always rebuild React after
frontend changes. The builder validates the Vite manifest and referenced bundle
paths, preserves binary assets, excludes build metadata and source maps, and prints
the ZIP SHA-256. Existing packages are preserved. The package includes only the
compiled public HTML/assets, application Python and runtime dependencies. It
contains neither Node/npm/node_modules nor the event database or private inputs.

Treat everything in a frontend build as public. Never put answers, credentials,
host packs or private event content into React source, `public/` or `VITE_*`
environment variables. The builder rejects unexpected build files; it cannot
determine whether a value inside a valid JavaScript bundle is confidential.

## Deploy the combined release

Reuse the backend's app settings and startup command `sh startup.sh`. Keep
`DJANGO_SETTINGS_MODULE=config.settings_production`,
`SCM_DO_BUILD_DURING_DEPLOYMENT=true` and `DISABLE_COLLECTSTATIC=true`.
No new frontend app setting or cross-origin API URL is needed. From PowerShell:

```powershell
$resourceGroup = 'REPLACE_WITH_RESOURCE_GROUP'
$appName = 'REPLACE_WITH_APP_NAME'
az webapp deploy --resource-group $resourceGroup --name $appName --src-path ".local/deploy/website-$release.zip" --type zip
```

Deploy before play or during a controlled maintenance pause. On each instance,
startup collects Django admin assets and the bundled React JS/CSS, then launches
Gunicorn. Existing signing secrets and the database stay in place. This frontend
integration itself adds no migrations; the subsequent Round 1 image feature
requires migration 0022 and [private image storage setup](ROUND1_IMAGE_CONTENT.md).
Use the backend runbook's single-session migration step for schema releases.
Keep the previous combined ZIP for a
schema-compatible rollback. Redeploying a backend-only ZIP will remove the React
pages from that release.

| Request | Served by / cache policy |
|---|---|
| `/`, `/login`, `/lobby` | React HTML through Django, `Cache-Control: no-store`. |
| `/rounds/{id}`, `/rounds/{id}/coding`, `/rounds/{id}/results` | Same shell on direct navigation and refresh. |
| `/missions/{token}`, `/staff/rounds`, `/staff/results`, `/staff/scores`, `/staff/roster`, `/staff/coding`, `/staff/buzzer` | Same shell; protected data/actions still require backend authorization. |
| `/static/frontend/assets/*` | WhiteNoise, with immutable caching for fingerprinted assets. |
| `/api/*`, `/admin/*` | Django API and administration; no SPA fallback. |
| Unknown routes, missing assets, `.env`, private filesystem paths | Remain unavailable; not rewritten to the React homepage. |

At Front Door, cache only public static assets. Disable caching for HTML pages,
authenticated APIs and admin. When adding the public domain, update Django's
explicit allowed hosts and HTTPS trusted CSRF origins, retaining the App Service
hostname for platform probes. Keep the backend origin restriction and private
database connectivity from the deployment plan.

## Verify on the deployed origin

Open `/`, then navigate directly to `/login`, `/lobby`, `/rounds/5` and
`/staff/buzzer`. Refresh each URL and check for successful JS/CSS loading. Sign in
with a rehearsal team and real staff roles, verify CSRF/session/logout behavior,
and confirm anonymous users cannot obtain protected API data. Check `/api/health`
and admin styling as well. A returned React shell does not grant access to a round.

Local checks cover the extracted production ZIP's shell/assets/cache headers and
mocked desktop/mobile user journeys. They do not certify deployed Azure routing,
credentials, private networking, WAF behavior or event capacity. Finish the
deployed rehearsal before participant release.

Round 5 content is added through the deployed admin independently of code packages;
see [adding Round 5 content after deployment](ROUND5_OPERATIONS.md#add-content-after-azure-deployment).

The build and static-file behavior follows [Vite's production build guidance](https://vite.dev/guide/build)
and [WhiteNoise's Django configuration](https://whitenoise.readthedocs.io/en/stable/django.html).
