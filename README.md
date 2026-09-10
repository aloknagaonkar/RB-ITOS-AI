# Market Strategy Lab

Independent Indian market research application, created from scratch in its own Git repository on `feature/pcr-foundation`. It has no imports, shared database, configuration files, or dependencies on the surrounding application. Run every command below from this project directory.

## First release

- React/TypeScript dashboard: fixed morning ATM, moving ATM and full-expiry PCR; three separate strike-level OI/change tables with totals, chart, input export, data health and versioned parameters.
- Pure Python calculation engine; contract OI comes from the provider, PCR is calculated locally.
- Separate recording worker with pause/resume, heartbeat, bounded network timeouts, retry backoff and one local collector lock.
- Upstox REST adapter: contract catalog, full option chain and underlying quote. Token stays in the backend environment.
- Raw responses, normalized observations, configuration versions, calculation results and morning anchors are persisted together.
- Deterministic replay verifies recorded calculations. This is not a historical trading backtest.
- SQLite for a zero-service local preview; PostgreSQL configuration and Docker Compose for development with PostgreSQL.

Automated orders, paper fills, entry/exit strategies, WebSocket streaming, stock screening and multi-provider failover are later milestones. This release cannot place orders. No live-account connection has been verified yet.

## Local setup (PowerShell)

Requirements: Python 3.11+ and Node.js 22.12+.

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e '.[dev]'
Copy-Item .env.example .env
npm --prefix frontend install --os=win32 --cpu=x64 --include=optional
npm --prefix frontend run build
.\.venv\Scripts\python.exe -m market_lab.cli seed-demo --count 90
.\.venv\Scripts\python.exe -m uvicorn market_lab.api:app --host 127.0.0.1 --port 8000
```

Open http://127.0.0.1:8000. The built UI is served by FastAPI. For frontend development, use `npm --prefix frontend run dev` and open port 5173; its API proxy uses port 8000.

In a second terminal, from this project directory:

```powershell
.\.venv\Scripts\python.exe -m market_lab.worker
```

Click **Start collection** in the dashboard. Closing the browser does not stop the worker. Click **Pause collection** to stop further attempts; an in-flight observation can still finish. Stop the worker with Ctrl+C. Only one worker/seed process may hold the local collector lock. The API may run separately.

Demo data is visibly labelled synthetic. Each worker tick advances one simulated market minute every five wall-clock seconds. Seeding starts at the configured morning anchor and uses the same recording/calculation pipeline. It does not represent the current market. Re-running the seed command appends observations; it does not reset data.

## Connect Upstox data

1. Put your access token in this project's `.env` as `UPSTOX_ACCESS_TOKEN`. Never commit it or paste it into the UI.
2. Pause collection. In Configuration, choose Upstox, set the correct underlying instrument key and an explicitly listed expiry, then save a new version.
3. Restart the worker to load the token, then start collection. API credentials and account entitlements must be checked against your subscription.
4. Start before the morning capture window to observe fixed ATM. A late first start correctly produces a missed anchor. Moving and full-chain calculations can still run when their inputs pass validation.

The adapter uses only GET requests to market-data endpoints. No order endpoint is implemented. Upstox OI update timestamps are unknown in the option-chain schema; recent retrieval does not establish field-level freshness. Underlying quote feed time is separate evidence, not proof of the last individual field update.

## PostgreSQL

```powershell
docker compose up -d db
```

Set `DATABASE_URL=postgresql+psycopg://lab:local_lab@localhost:5432/market_lab` in `.env`, then restart the API and worker. This creates a separate database; it does not migrate existing SQLite recordings. The Compose password is for local development only. PostgreSQL runtime verification requires an available Docker/PostgreSQL instance; SQLite is the verified preview path.

## Checks

```powershell
.\.venv\Scripts\python.exe -m pytest -c pyproject.toml tests -q
.\.venv\Scripts\python.exe -m ruff check --config pyproject.toml backend tests
npm --prefix frontend run build
.\.venv\Scripts\python.exe -m market_lab.cli replay
```

Dependency versions for the validated build are captured in `requirements-lock.txt` and `frontend/package-lock.json`. Use `pip install -r requirements-lock.txt` then `pip install -e . --no-deps` to reproduce the Python environment; use `npm --prefix frontend ci --os=win32 --cpu=x64 --include=optional` for the UI on Windows. Omit platform flags on other operating systems.

## Design and limitations

Read [architecture](docs/architecture.md), [PCR specification](docs/pcr-spec.md) and [delivery checklist](docs/delivery.md).

The server is intended for local use bound to loopback. It has host/origin checks, but no user authentication or multi-user authorization. Do not expose it publicly. The initial session gate covers weekday regular hours, not exchange holidays or special sessions. Schema creation is for this first release; migrations, retention, backups and distributed collector leases are pending. The dashboard displays the latest 240 observations for the active version; the database retains earlier records and API inspection/replay supports previous configuration IDs.
