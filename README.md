# Independent Hilega Historical Session Selector — UI-only fix

Fixes first integration: the Hilega panel no longer inherits the original ALL3 replay's date. Instead it obtains available Hilega dates from `/api/live-shadow/hilega-historical/sessions`, defaults to the most recent available date, and lets you select that day's historical capture (prefer a capture with a manifest). September 23 d4 should be available from the confirmed API response.

No backend, live shadow worker, strategy logic, or historical evidence changes.

## Installation

Unzip outside the repository and from `~/RB-ITOS-AI` run:

```bash
python /tmp/hilega-ui-independent-session-fix/install.py --repo "$PWD" --check
python /tmp/hilega-ui-independent-session-fix/install.py --repo "$PWD" --apply
cd frontend && npm run build
```

Since the API statically serves `frontend/dist`, a successful `npm run build` updates the served files without an API or worker restart. Hard-refresh the browser (Ctrl+Shift+R). If the old page persists, compare the JS asset served by `curl -s http://127.0.0.1:8123/` with the current `frontend/dist/index.html`, and inspect your reverse proxy cache.

The installer validates the existing v1 integration, creates backups of both modified frontend files, and refuses to overwrite unexpected changes. It is idempotent after successful application.

This view is for *manual historical inspection*, not proof of exact historic/live parity. The chart uses historical audit five-minute OHLC; missing data remains missing.
