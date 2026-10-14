# Sandbox worker-integrated daily arming — no cron

This replaces the proposed cron approach. The existing Sandbox basket-v2 serve loop runs the daily premarket arming check internally. Installer removes only our named managed cron block if it exists, preserving all other cron jobs. No ChatGPT scheduled reminder is created.

The worker must already be running. During weekdays09:00–09:14 IST, its normal poll loop attempts automatic arming once per five-minute interval (09:00,09:05,09:10 buckets; starting within a bucket attempts immediately). It arms the current IST date and verifies the current configured strategy against HILEGA_V2_ALIGNMENT_DUAL_EXIT. An already armed date is preserved without resetting baseline_source_sequence. No first-time daily auto-arm happens at/after09:15. If today's session is already armed, the restart does not require rearming.

All prior safety checks are retained: no open legs or uncertain requests; manual kill switch and entries_blocked respected; Sandbox-only mode; strategy match; configuration enabled, lot/token presence; existing basket.arm() legacy journal/dispatch reconciliation and audit-chain validation. No token is printed. This helper never submits orders and never enables real-market execution. It holds the existing basket worker lock while checking/arming and does not spawn another worker.

Weekends skipped. Optional holidays/disabled dates remain a JSON array in data/live-observation/hilega-upstox-sandbox-v2/auto-arm-disabled-dates.json. Exchange holidays are not automatically fetched; unlisted weekday holidays may be armed but require a same-date strategy signal for any order intent.

## Install once from repository root

```bash
tar -xzf hilega-sandbox-worker-autoarm.tar.gz
source .venv/bin/activate
python sandbox_worker_autoarm_bundle/install.py --check
python sandbox_worker_autoarm_bundle/install.py
bash scripts/stop_hilega_upstox_sandbox_worker.sh
bash scripts/start_hilega_upstox_sandbox_worker.sh
bash scripts/status_hilega_upstox_sandbox_worker.sh
```

The installer guards a unique serve-loop anchor and compiles both resulting modules before edits. It adds backend/market_lab/hilega_sandbox_daily_autoarm_v1.py and inserts one invocation in the serve loop of backend/market_lab/hilega_upstox_sandbox_basket_v2.py. It backs up changed files and the previous user-crontab (when our managed block exists) under backups/sandbox-worker-autoarm-TIMESTAMP. Already modified modules can be reapplied without duplicate hooks. No strategy module, execution policy, API, live-shadow or full application restart is required.

The cron block removal is scoped strictly to BEGIN/END HILEGA_SANDBOX_DAILY_AUTOARM. If you never installed the cron version, this is a no-op. A stopped worker cannot perform automatic arming; keep its existing startup process enabled. This update does not install an OS boot service.

## Status and diagnosis

```bash
bash scripts/status_hilega_upstox_sandbox_worker.sh
cat data/live-observation/hilega-upstox-sandbox-v2/auto-arm-status.json
tail -n 40 data/logs/hilega-upstox-sandbox-worker.log
```

auto-arm-status.json identifies scheduler SANDBOX_WORKER, current attempt day/bucket and any blocked reason. Errors do not clear block flags. If the worker only starts after09:15 and today is not armed, use the existing manual arming procedure after checking reconciliation. The running process reloads controls normally.

## Verification

21 tests passed:16 shared arming guards/action tests,4 worker scheduling/idempotence tests,1 installer test verifying serve-loop update and removal of only our cron job. Tests inject adapters, clock and a nonblocking lock context; no broker request or actual cron mutation occurs. Production uses the existing filelock dependency and same worker lock path. Real VM/broker integration has not been executed here. Syntax compilation and local installer apply/reapply checks passed.

```bash
python -m unittest discover -s sandbox_worker_autoarm_bundle -p 'test_*.py'
```

Deployment is performed by running the installer on your VM. This chat prepared and tested the bundle only.
