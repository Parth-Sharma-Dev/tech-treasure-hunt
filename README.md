# Tech Treasure Hunt

Competition website for the AI Nexus Club, CSE Department, SKIT Jaipur, Tech-Pravah 26.

The website is being built to support team login, QR-based missions, answer submission, Round 1 scoring, and organizer-reviewed results and qualification through five rounds.

The current implementation includes a responsive event page, competition/evidence models, draft content preparation and rule approval in Django admin, team sign-in, a participant lobby, organizer round controls, server clocks, QR/fallback mission access, answer submissions, team progress and signed receipts. Organizer-reviewed Round 1 standings, provisional/final publication, incident review and final qualification are available. Production deployment remains deferred.

Round controls support READY → LOBBY → LIVE, pause/resume, explicit extensions and ending. PostgreSQL supplies the authoritative time; frozen intervals do not consume the active budget. Staff actions require a reason, a UUID `action_id` and the latest `expected_version`. Retrying the identical action returns its original response; stale or changed actions are rejected. Controls cannot reopen ENDED rounds or paper play. Extensions are audited separately from pause duration.

Open `/staff/rounds` for the organizer controls screen and sign in through its Django admin link. Staff need `competition.control_round`; demo account `DEMO-content` has this permission. Draft rounds still require independent mission verification and rule approval in admin before they become READY. The screen preserves an unconfirmed action in browser session storage and retries the identical UUID/payload after a lost response or reload.

Staff can read `GET /api/staff/rounds` and submit CSRF-protected controls to `POST /api/staff/rounds/{id}/control`, with `action` set to `open_lobby`, `start`, `freeze`, `resume`, `extend` or `end`. `extend` additionally requires a positive `extension_ms` (at most 24 hours per action). Reads report expired live rounds as ENDED immediately, without writing evidence. To persist completed intervals after a delayed job, run `.venv/Scripts/python backend/manage.py end_expired_rounds --actor <controller-username>`; intervals are capped at the original deadline.

The participant lobby displays live, paused and ended round clocks. It refreshes roughly every 15 seconds with jitter, suspends polling in hidden tabs and refreshes on return. Countdown estimates use monotonic elapsed time; all eligibility and cutoff decisions remain on the server.

The mission API supports QR tokens and separate random fallback codes. `GET /api/missions/{token}` records no visit and reveals no unopened clue. CSRF-protected `POST /api/missions/open` takes either `token` or `fallback_code`; new clues open only during live online play. Previously opened clues remain readable after pause/end. Competitive missions are isolated from practice and from demo/live cohorts.

Submit four ASCII digits to `POST /api/missions/{token}/submit` with a UUID `Idempotency-Key` header. PostgreSQL admission time is read after shared Round and exclusive Team locks. Only newly evaluated answers consume the team-wide active-time quota; cooldowns exclude paused time. Decisions and completions commit together. Retrying the same key/payload returns the original outcome; changing the answer or mission conflicts. A lost response requires checking `GET /api/rounds/{round}/attempts/{key}` and retrying the same attempt, rather than inventing an incorrect result.

`GET /api/rounds/{round}/state` returns your team's current effective score and earned keywords separately from historical decisions. `GET /api/me/receipts` returns your own signed accepted receipts. Receipts use a separate signing purpose from answer HMACs; preserve both Django and answer secrets across restarts. A void removes current credit while preserving original accepted evidence and receipts.

Visit `/missions/{token}` from a QR link, then explicitly open the mission. Alternatively, enter its separate fallback code in the lobby. Submit a four-digit answer while live. The browser saves an unconfirmed attempt's UUID and original answer in session-scoped storage bound to your team and mission. After a lost response or reload, use **Check saved attempt** to fetch the durable decision before retrying the identical request. Signing out clears this pending data. Accepted receipts can be saved from the progress panel.

## Reviewed Round 1 results

Open `/staff/results` (linked from round controls). `DEMO-content` prepares proposals; `DEMO-verifier` independently approves them. Select an ended round, inspect its private standings and integrity checks, then submit a provisional proposal with a public summary. In a separate staff session, review the proposal and approve publication. After the full appeal window and resolution of material issues, prepare a final proposal, confirm evidence coverage and supply reserve-clue evidence if the cutoff is tied. The second reviewer confirms the final evidence and publishes it.

Teams use the lobby's published-results link or `/rounds/{database-round-id}/results`. They see published snapshots only, their highlighted row, appeal timing, final qualification and immutable publication history. Public summaries are visible to teams; private incident and reserve-clue evidence references stay on the staff desk. Use **Retry same results action** to recover an unconfirmed staff write in the original browser session.

Standings count non-voided effective completions and break score ties by the active time of the last counted completion. Zero-score teams remain tied; team-code sorting stabilizes display only. Available non-voided competitive missions determine the denominator. Withdrawn/disqualified teams retain evidence but cannot qualify.

An authorized controller/adjudicator proposes a result using the current evidence digest and control version. A different staff member with both `publish_results` and `verify_evidence` approves it. Each publication creates an immutable snapshot and audit event. Provisional publications never grant qualification; revised provisional snapshots visibly supersede the previous revision and restart the full configured appeal window.

Final publication requires a preceding provisional snapshot, the completed appeal window, two evidence confirmations, no open material incidents, and consistent rules/clock/completion/accepted-receipt evidence. A cutoff tie requires all tied teams in the declared supervised reserve-clue order, a reason and evidence references, reviewed with the final proposal. Qualification comes only from the latest attempt's final snapshot. Ordinary publication cannot replace finalized results.

Staff endpoints: `GET /api/staff/results`, `GET /api/staff/rounds/{id}/results`, `POST /api/staff/rounds/{id}/publish` (`action: propose` or `approve`), and `POST /api/staff/rounds/{id}/incidents` (`action: open` or `close`). Writes require CSRF, an action UUID and reason. Incident closure requires a different authorized verifier and supporting evidence references; it does not adjust scores. `GET /api/rounds/{id}/results` exposes published snapshots/history to authenticated teams in the same cohort, never private previews or pending proposals.

This workflow currently supports online Round 1 completion results. Later-round imported rankings, paper reconciliation, score-changing adjudication and post-final corrections remain separate development work. Automated integrity checks cannot prove that entirely missing records never existed; both reviewers must check evidence coverage and record any known gap as a material incident.

Qualification does not enable native hunt scoring for externally judged rounds: their mission-open and answer APIs explicitly refuse native play. Later-round scores will use the separate reviewed import workflow.

An optional full browser integration test runs against Django HTTP and an isolated PostgreSQL test database. Start Vite on port 5173 and install Playwright Chromium first, then run in PowerShell:

```powershell
$env:TTH_BROWSER_INTEGRATION = '1'
.venv/Scripts/python -m pytest backend/tests/test_browser_gameplay.py
.venv/Scripts/python -m pytest backend/tests/test_results.py -k browser_provisional
Remove-Item Env:TTH_BROWSER_INTEGRATION
```

These cover organizer start/pause, team login, explicit QR opening, an answer with leading zeros, scoring, signed receipts/logout, and a separate two-person provisional-to-final publication journey. The publication test advances only its isolated test clock after provisional publication; application requests cannot skip the actual appeal window. The ordinary backend suite skips these browser-dependent tests.

## Requirements

- Python 3.13 (tested with 3.13.13).
- Node.js 24 (tested with 24.15.0) and npm.
- PostgreSQL 18 (tested with 18.6), either installed locally or using Docker Compose.

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

For a native Windows PostgreSQL installation, set `POSTGRES_HOST=127.0.0.1` and its actual port in `.env` (an installation alongside another running database may use port 5433). Use a dedicated application role/database rather than the PostgreSQL administrator account. The role needs `LOGIN` and `CREATEDB` for local pytest runs, and ownership of the application database. Add the installed `bin` directory to your terminal's PATH if you want to use `psql`, `pg_dump` or `pg_restore` directly.

The Docker configuration uses a separate `postgres18_data` volume. An older PostgreSQL 17 volume is not upgraded in place: preserve it and transfer data with a logical dump/restore before switching versions. PostgreSQL 18's container mounts data at `/var/lib/postgresql`.

In a second terminal:

```powershell
cd frontend
npm ci
npm run dev
```

Open **http://127.0.0.1:5173**. Vite proxies API, admin and Django static requests to port 8000. Use this same frontend origin for browser requests so Django sessions and CSRF cookies work together. An optional staff account can be created with `.venv/Scripts/python backend/manage.py createsuperuser`; access admin through **http://127.0.0.1:5173/admin/**.

The database volume persists across stops. Stop it without deleting data using `docker compose --env-file .env -f infra/compose.yaml stop`.

## Demo data and content preparation

With the environment configured and migrations applied:

```powershell
.venv/Scripts/python backend/manage.py seed_demo
```

This creates two fictional teams, five draft rounds, two synthetic competitive missions, an isolated practice mission, and separate content/verification staff accounts. Random credentials are saved to the ignored `.local/demo-credentials.json` file. Repeating the command preserves existing passwords and content. Demo seeding requires development mode and refuses a database containing non-demo teams or rounds.

Open `/login` and sign in with a demo team code and its generated password. The lobby shows your team's browser-session count, round preparation status and a practice clue. Practice answers preserve leading zeros and award no competition points. Signing out revokes only the current browser session. Demo competitive missions remain locked until staff independently verify them, approve the rules, mark the round READY and start it through the controls screen.

Demo rounds remain DRAFT: they do not stand in for approved competition settings or verified event content. Content staff can edit draft rounds and missions in Django admin. Answers are entered privately and stored as mission/version-bound HMACs using `ANSWER_HMAC_KEY`; editing mission content invalidates its previous verification. An authorized independent verifier can attest to checking a mission end to end.

Before READY, configure the rule version, delivery method, advancement counts, active budget, staff-owner IDs, capacity and all policies. A verifier approves the current settings, then a controller marks the round READY. Missing settings, unverified missions, self-verification and an unapproved short roster block readiness. Changing signed settings requires new approval. READY freezes the rules snapshot and mission content; evidence and scoring records are read-only in admin. Later rounds currently accept only external delivery modes.

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
| `POST /api/auth/login` | Signs in using `team_code` and `password`; accepts a validated `return_to` path. |
| `POST /api/auth/logout` | Revokes this browser's team session and signs out. |
| `GET /api/me` | Returns the authenticated team's identity, session count and permitted round status. |
| `GET /api/practice` | Returns the isolated practice clue for this team's environment. |
| `POST /api/practice/submit` | Evaluates a four-digit practice answer without scoring or competitive evidence. |
| `POST /api/staff/teams/{team}/sessions/{session}/revoke` | Audited staff removal using `action_id` and `reason`; requires round-control permission. |

Team login permits four active browser sessions, allocated under a PostgreSQL team lock. Five incorrect passwords within a 60-second login window temporarily block further login attempts for that team; this is separate from gameplay limits. Browser sessions expire after 12 hours. Staff can inspect and revoke stale browsers through Django admin without seeing their session keys. Revocation leaves other teammates signed in, and session-version changes invalidate old access. Team credentials cannot enter staff administration.

Authenticated API writes need an `X-CSRFToken` header obtained from `/api/auth/csrf`; login rotates that token and includes the current `csrf_token` in its response. Team identity is always derived from the authenticated session, never a supplied team ID. Later-round access requires qualification in the preceding round's final published snapshot.

API responses include a generated `X-Request-ID` header and `Cache-Control: no-store`. PostgreSQL is the only configured database; there is no SQLite fallback. Secrets, local database data and development-only planning documents are not committed.
