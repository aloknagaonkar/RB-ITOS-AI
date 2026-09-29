# Live UI bootstrap performance fix

The browser capture showed the 405 KB JS bundle taking 1.4 minutes, and `/api/state` returning 2.2 MB in 24–32 seconds while polling every three seconds. This patch adds response compression; the app polls one observation every 15 seconds with no overlapping requests, retains full PCR history only when PCR workspace is open, and remembers the selected workspace. Default `/api/state` semantics remain 240 rows for other clients.

## Apply now to API/UI only

From the VM, put this ZIP and its extracted `apply_live_ui_performance.py` and `restart_api_only.sh` in one directory. In `~/RB-ITOS-AI` run:

```bash
python /path/to/apply_live_ui_performance.py
source .venv/bin/activate
PYTHONPATH=backend python -m pytest -q tests/test_storage_api.py
cd frontend && npm run build && cd ..
```

Do not proceed if the installer stops or tests/build fail. Review `git diff -- backend/market_lab/api.py frontend/src/App.tsx tests/test_storage_api.py` and `git diff --check`. The patch was prepared from the uploaded ZIP and refuses changed files. Backups are `.pre-live-ui-perf.bak`; do not stage them.

To load the updated API without stopping the live shadow worker, from repo root run:

```bash
bash /path/to/restart_api_only.sh
```

This script validates the managed API PID before signaling that process and verifies the live shadow worker PID before and after. Never run `./scripts/restart.sh` during market hours; it stops the worker.

In Chrome DevTools uncheck `Disable cache`, close DevTools, and refresh once. The browser should fetch a small `/api/state?history_limit=1` response. If `PCR workspace` is selected, one full `/api/state` request is expected for its history; clicking Live Shadow cancels that fetch.
