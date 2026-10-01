# Tech Treasure Hunt

Competition website for the AI Nexus Club, CSE Department, SKIT Jaipur, Tech-Pravah 26.

The website is being built to support team login, QR-based missions, answer submission, Round 1 scoring, and organizer-reviewed results and qualification through five rounds.

The current scaffold includes a responsive event page, a Django API, database-backed session configuration, and local PostgreSQL tooling. Team login and gameplay are not implemented yet. Production deployment is not configured.

## Requirements

- Python 3.13 (tested with 3.13.13).
- Node.js 24 (tested with 24.15.0) and npm.
- Docker Compose for the bundled PostgreSQL 17.11 service, or an existing PostgreSQL 17 instance.

## Local setup

Run these PowerShell commands from the repository root:

```powershell
Copy-Item .env.example .env
python -m venv .venv
.venv/Scripts/python -m pip install -r backend/requirements.txt
docker compose --env-file .env -f infra/compose.yaml up -d --wait
.venv/Scripts/python backend/manage.py migrate
.venv/Scripts/python backend/manage.py runserver 127.0.0.1:8000
```

Copy the environment template only on first setup; preserve your existing `.env` on subsequent runs. The supplied credentials are for local development only. To use an existing PostgreSQL server, create the database/user named in `.env`, update its connection settings, and omit the Docker command. The database user needs permission to create a test database when running the integration suite.

In a second terminal:

```powershell
cd frontend
npm ci
npm run dev
```

Open **http://127.0.0.1:5173**. Vite proxies API, admin and Django static requests to port 8000. Use this same frontend origin for browser requests so Django sessions and CSRF cookies work together. An optional staff account can be created with `.venv/Scripts/python backend/manage.py createsuperuser`; access admin through **http://127.0.0.1:5173/admin/**.

The database volume persists across stops. Stop it without deleting data using `docker compose --env-file .env -f infra/compose.yaml stop`.

## Validation

From the repository root, with PostgreSQL running:

```powershell
.venv/Scripts/python backend/manage.py check
.venv/Scripts/ruff check backend
.venv/Scripts/ruff format --check backend
.venv/Scripts/python -m pytest backend
```

Foundation tests can also run without a database: `.venv/Scripts/python -m pytest backend/tests/test_foundation.py`. This subset does not validate database integration or locking.

From `frontend`:

```powershell
npm run build
npx playwright install chromium
npm run test:e2e
```

Browser tests cover desktop/mobile layouts and connected/unavailable states with mocked health responses. They start Vite automatically; database integration is covered separately by pytest.

## API endpoints

| Endpoint | Purpose |
|---|---|
| `GET /api/health` | Returns `200` when a database probe succeeds, or a redacted `503` when unavailable. |
| `GET /api/auth/csrf` | Provides a CSRF token and sets its cookie for future authenticated write requests. |

API responses include a generated `X-Request-ID` header and `Cache-Control: no-store`. PostgreSQL is the only configured database; there is no SQLite fallback. Secrets, local database data and development-only planning documents are not committed.
