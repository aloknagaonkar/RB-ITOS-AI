# Live display API timeout correction

The observer is connected and has five cached instruments. The 10-second timeout occurs on the local API, not on quote subscription. The previous faster-polling patch still rebuilt dashboards by rereading the complete audit file. Concurrent status, candle and quote requests amplified that cost. This correction removes full audit reads from quote requests and shares a background incremental display cache.

## Changes

- Quote and trade-dashboard endpoints return a precomputed display dashboard; request threads do not scan/project the audit history.
- Directional/legacy status display readers share a per-file background cache. Initial history is scanned once; subsequent work reads appended complete JSONL records only. Partial final records are retried, and rotation/truncation resets the cache. It never modifies the source journal or takes its writer lock.
- Initial cache loading returns explicit HTTP503 + Retry-After instead of blocking or reporting a false zero-trade result. Automatic polling retries. The full journal and explicit hash verification remain unchanged.
- Audit-only candle UI uses recorded indicator/decision evidence instead of reconstructing a second indicator history. Normal historical/reconstruction routes retain their existing behavior.
- Combined live UI requests today's directional audit first and avoids fetching the legacy full-chain audit index when promoted rows are available.
- Browser errors identify display timeout/cancellation, not an aborted strategy signal.
- Active-contract lot metadata can reload after observer restart through a read-only contract-catalog GET on a daemon thread. This leaves the ranking catalog and evaluator state unchanged. Prices, expiry/lot validation, 10-second freshness and depth checks are retained.

No strategy engine, order worker, event bridge, rules, sandbox controls or recorded trade results change. The installer checks protected strategy/order source hashes before/after writes. No tests/build were run locally; validate on the VM.

## Apply and validate

Close dashboard browser tabs temporarily to stop the old polling load. Leave the strategy worker and sandbox unchanged. Download this ZIP into ~/RB-ITOS-AI, then:

```bash
cd ~/RB-ITOS-AI
(
set -e
unzip hilega-live-timeout-fix.zip
.venv/bin/python hilega-live-timeout-fix/install.py
.venv/bin/python hilega-live-timeout-fix/install.py --apply
PYTHONPATH=backend:. .venv/bin/python -m pytest -q \
  tests/test_hilega_ui_journal_cache_v1.py \
  tests/test_hilega_active_live_marks_v1.py \
  tests/test_hilega_combined_promotion.py \
  tests/test_hilega_execution_dispatch_validation.py
node tests/hilega_live_polling_vm.cjs
npm --prefix frontend run build
bash scripts/restart_hilega_ui_api_safe.sh
bash scripts/stop_hilega_policy_observer.sh
bash scripts/start_hilega_policy_observer.sh
)
```

Reopen the dashboard with Ctrl+Shift+R. Startup may briefly show UI_AUDIT_CACHE_WARMING_OR_ERROR or UI_TRADE_CACHE_WARMING_OR_ERROR with error=null while existing history loads in the background. The API should respond promptly with this explicit status, then the rows populate automatically. A non-null error requires investigation, not bypassing the cache or wiping journals.

## Verify

```bash
curl -sS --max-time 5 -w '\nHTTP %{http_code}; seconds %{time_total}\n' \
  http://127.0.0.1:8123/api/live-shadow/hilega-directional/active-live-marks
bash scripts/status_hilega_policy_observer.sh
```

Expected after cache loading and current ticks: model HILEGA_ACTIVE_LIVE_MARKS_V1, stream_connected=true, actual timestamps and LIVE legs. Missing metadata/quotes remain unavailable; no fixed lot or fabricated P&L is substituted. Validated lot metadata should restore rupee estimates, subject to bid depth and freshness.

Confirm the decision table repopulates and future 5m checkpoints arrive without a browser refresh. Strategy worker PID should remain unchanged during the API restart. If restart refuses to stop an old busy API, share the output; do not force-kill or restart the strategy worker.

The installer preserves installed promotion/inspection changes by narrowly matched transformations; it stops on unexpected source rather than overwriting whole files. Timestamped backups are created under backups/hilega-live-timeout-fix-*.
