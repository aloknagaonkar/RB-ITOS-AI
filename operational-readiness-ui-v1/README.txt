UI-only operational readiness monitor v1

From the RB-ITOS-AI project root:
  .venv/bin/python operational-readiness-ui-v1/apply.py
  PYTHONPATH=backend:. .venv/bin/python -m pytest -q tests/test_operational_readiness_v1.py tests/test_shadow_session_recovery.py
  (cd frontend && npm run build)
  bash scripts/restart.sh
  bash scripts/status.sh
  curl --max-time 10 -sS http://127.0.0.1:8123/api/data-health/readiness

The installer prevalidates source markers and creates backups under data/backups/operational-readiness-TIMESTAMP. It stops if the source layout differs. Do not apply twice. Strategy rules, sandbox arming, trading journals and order placement are not modified.

The monitor starts through start.sh/restart.sh and continues independently every 15 seconds, including overnight. Keep it running before 08:45 IST. Stop through stop.sh. UI alerts appear across workspaces; the existing Data health workspace shows detailed readiness checks and recent notifications. There are no email/Telegram/Slack notifications.

Schedule: 08:45 validate warmup; 08:50 onwards repair incomplete operational caches; 09:00 analytics authentication and operational readiness; 09:10 final readiness; 09:15-15:30 live checks. Historical scans repeat every 5 minutes while active. Repair occurs only before 09:15, fetches real historical candles and validates before replacement; existing helper preserves originals. Optional .env HILEGA_READINESS_AUTO_REPAIR=0 disables monitor-driven repair.

Pre-market indicator warmup is isolated: it never invokes the order or live strategy process. Weekends are OUT_OF_SESSION. No exchange-holiday calendar is configured: missing/empty calendar dates remain explicit unknowns; on a weekday holiday live checks can warn after open. This does not certify exchange-session coverage.

Checks: API, configured strategy, independent shadow-worker health (60-second freshness), component errors/backoff, current-session bootstrap after first completed-candle grace, five-minute candles/decisions (90-second scheduling grace; cutoff capped at 14:55), sandbox running/armed/session/strategy/kill/uncertainty, fresh accepted entry dispatch after 30 seconds. Recovered entries are explained rather than automatically dispatched. Alerts persist in state.json with first failure, last detection, last successful check, reminder and recovery history. Reminders every 5 minutes; persistent faults escalate after 60 seconds. Stopped/stale monitor is surfaced by API/UI independently.

Credential scope: analytics token acceptance checked with a read-only NIFTY quote GET every 5 minutes after 09:00. Sandbox token presence and control/dispatch health are checked. Sandbox authentication cannot be independently certified without an appropriate supported read-only endpoint; the monitor does not place a test order. READY describes the configured operational checks, not broker-fill guarantees.

Artifacts:
 data/live-observation/operational-readiness-v1/state.json
 data/logs/operational-readiness.log
 data/operational-readiness.pid

The API must be restarted to load the route. The shadow worker must be restarted to publish detailed safe candle-validation errors. Existing operational warmup repair errors now include the affected historical date. Do not copy abandoned recovered-display prototypes: they are not in this bundle.
