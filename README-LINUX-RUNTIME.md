# Linux runtime patch

This version is aligned to the existing Windows runtime scripts in the project.

Existing Windows source of truth:

- `scripts/platform.ps1`
- `start.cmd`
- `stop.cmd`
- `status.cmd`
- `restart.cmd`

The existing runtime entry points are:

```text
python -m market_lab.runtime api
python -m market_lab.runtime worker
```

The API health endpoint is:

```text
http://127.0.0.1:8123/api/health
```

The Python runtime itself writes service metadata to:

```text
data/runtime/api.json
data/runtime/worker.json
```

Logs are written under `data/logs`.

## Upstox token

Create `.env` from the existing `.env.example` or from `.env.linux.example`:

```bash
cp .env.example .env
nano .env
chmod 600 .env
```

Set:

```text
UPSTOX_ACCESS_TOKEN=<current Upstox access token>
```

Never commit `.env`.

## Linux setup

From the repository root:

```bash
python3 -m venv .venv
./.venv/bin/python -m pip install -r requirements-lock.txt
./.venv/bin/python -m pip install -e . --no-deps

npm --prefix frontend ci
npm --prefix frontend run build

chmod +x scripts/start.sh scripts/stop.sh scripts/status.sh scripts/restart.sh
```

## Runtime

```bash
./scripts/start.sh
./scripts/status.sh
./scripts/restart.sh
./scripts/stop.sh
```

Logs:

```bash
tail -f data/logs/api.log
tail -f data/logs/api-error.log
tail -f data/logs/worker.log
tail -f data/logs/worker-error.log
```

The Linux scripts intentionally mirror the current PowerShell behavior:
API starts first, worker second, worker stops first, API second, and `/api/health`
is checked on port 8123.
