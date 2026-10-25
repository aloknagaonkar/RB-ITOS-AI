# Allocation-aware installed --watch subprocess validation

No installation/apply, real token loading, Upstox requests, active app DB writes,
.env changes or strategy changes. Uses actual newly installed CLI/modules with
exact source hashes; old pinned runners are not reused as proof for new source.

Run unit tests first on VM. Only Python AST syntax checked in preparation; tests,
child processes and demonstrations were NOT run locally.

cd ~/RB-ITOS-AI
set +e
PYTHONPATH=backend:. .venv/bin/python -m pytest -q hilega-production-funded-watch-validation/test_runner.py
PYTHONPATH=backend:. .venv/bin/python -u hilega-production-funded-watch-validation/run.py --output data/research/hilega-funded-watch-validation-v1

New isolated output directory required. Original working app is not paused,
resumed or read by this runner; actual workspace stays PAUSED/unfunded/reader OFF.
Children receive sanitized environment, empty private env file, isolated cwd and
DB/source paths. Real account tokens/control keys are not inherited. This test
does explicitly Resume ONLY the isolated synthetic simulator DB.

Checks: actual reader missing funds blocks Resume; --synthetic-cash100000 refreshes
fictional cash each5s without arming; explicit Resume then future completed5m
synthetic confirmed bearish entry; central reservation6600 before fake fill65;
Pause after reconciled fill keeps established position/hold; matching journal
EXIT while paused closes and releases after verified flat; duplicate polling;
restart without cash refresh;30s expiry independent of healthy heartbeat; blocked
Resume; funded recovery stays paused; SIGKILL heartbeat expiry; driver calls same
watchdog method; restart releases kernel lease and never replays prior BUY/SELL.

The initial existing bullish entry is only a baseline synthetic history event.
Entry must be newer than Resume. The runner waits for the NEXT genuine5m wall-clock
boundary, up to5 minutes, without backdating control state or changing clocks.
Overall allow roughly1–7 minutes. Progress prints every10 seconds during the wait.
No live-market session is needed. All events/prices/fills/cash are synthetic.

Entry and exit can occur within the same5m boundary as separate artificial journal
records; this tests dispatch/gates, NOT strategy-generated timing or profitability.
No indicator replay, live quotes, real cash/fills, broker ownership or production
readiness claim. One instrument only. No UI/browser is launched. API background
watchdog scheduling is covered by prior tests, not re-proved here.

Each wait bounded; failure writes report.json and summary.md with worker logs.
Do not kill broad process groups; only Popen children created by the runner are
signalled. Normal/caught failures clean up its own children. If the driver itself
is SIGKILLed, test children may remain: identify ONLY exact isolated --source path.
New trading-session rollover during this run is outside its supported schedule;
run within one IST day. A delayed VM can fail bounded timing checks; do not relax
entry age/freshness gates to force PASS.

Generated files include synthetic snapshots, orders and fills. Production remains
disabled throughout. Real funds reservation/debit integration and market-hours
quote validation remain pending after this check.
