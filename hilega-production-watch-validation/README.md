# Real --watch process lifecycle, isolated simulator only

No installer/apply, active service restart or .env edits. Run from repository root
on the Linux VM after bridge-health installation. Dependency modules and the CLI
are hash checked against the delivered health milestone. Unexpected code blocks.

First: PYTHONPATH=backend:. .venv/bin/python -m pytest -q hilega-production-watch-validation/test_watch.py
Then: PYTHONPATH=backend:. .venv/bin/python -u hilega-production-watch-validation/run.py --output NEW_DIRECTORY

The runner launches the actual installed scripts/hilega_production_simulator_bridge.py
--watch --synthetic-fills with the actual unmodified simulator modules. An empty
private env file, sanitized child environment, isolated cwd, test journal and
separate DB are passed explicitly. Broker/control tokens and active DB settings
are not inherited. It never controls the actual app strategy or Sandbox worker.

Checks: baseline existing synthetic entry; healthy PID/heartbeat; second worker
rejection without changing control owner; appended candidate and paused confirmed
entry; background repeated polls; graceful SIGINT; restart cursor; isolated Resume;
SIGKILL; heartbeat expiry; watchdog durable Pause; stale Resume rejection; kernel
lock release; recovered worker remains paused; graceful final stop flat.

Signals and prices are synthetic. No BUY is expected: the only Resume occurs
after the journal entries are consumed and before killing the test worker.
Real entry/fill/exit paths were exercised in earlier recorded-journal tests.
No market session is needed. No P&L, real broker execution or live-market
readiness claim. The API scheduler itself is not launched; the driver calls the
same watchdog method after wall-clock heartbeat expiry. Prior API watchdog tests
cover scheduling separately.

Progress prints immediately. Normal runtime is roughly 30–90 seconds but depends
on VM startup and disk latency; each wait is bounded. Slow startup causes FAIL,
not an indefinite wait. Reports include per-check status and worker logs.
Do not use the same output directory twice. Temporary children are always stopped
on caught errors. If the driver itself is SIGKILLed, test children can remain:
identify them only by the exact isolated --source path in this output directory.
Never kill broad Python/strategy worker process groups.

The runner sends SIGINT and SIGKILL ONLY to Popen objects it created. Live app
databases and journal are never opened. Synthetic journals/logs/DBs stay in output.
Final report.json and summary.md are generated on normal completion or caught
lifecycle failure. Missing imports/file/hash guards can fail before a report.

Only Python AST syntax was checked during preparation. No tests, subprocesses,
replay or frontend build were run locally. VM unit tests and lifecycle runner
must both pass. Production execution remains disabled after validation.
