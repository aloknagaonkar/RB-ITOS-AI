# Installed durable integration: end-to-end isolated validation

No installation/apply step. Tests the just-installed durable integration via:

- A real optional reader --watch process and synthetic chained journal.
- The installed workspace router and workspace_lifespan background monitor in a
  temporary minimal FastAPI/uvicorn process on a prebound unused loopback port.
- The installed hilega_production_control.py CLI pointed explicitly to that port.
- The same authenticated status endpoint used by the UI, including Origin checks.
- Explicit synthetic funding, simulated prices and simulated fills only.

The normal API on port 8123, running strategy worker, its journal, the default
workspace DB, actual control key and actual Upstox credentials are not used.
A random temporary control key is created mode 0600 in the new output directory.
Child processes receive a minimal environment with broker observation disabled.
The installed source hashes, policy and version are checked before running.
If a hash mismatch appears, do not bypass it; share the diagnostic for review.

## Commands

```bash
cd ~/RB-ITOS-AI
set +e
PYTHONPATH=backend:. .venv/bin/python -m pytest -q \
  hilega-production-installed-e2e-validation/test_runner.py
```

After tests pass, run in the background so an SSH disconnect does not interrupt it:

```bash
mkdir -p data/research
nohup env PYTHONPATH=backend:. .venv/bin/python -u \
  hilega-production-installed-e2e-validation/run.py \
  --output data/research/hilega-installed-e2e-validation-v1 \
  > data/research/hilega-installed-e2e-validation-v1.log 2>&1 < /dev/null &
echo "Validation PID: $!"
```

Check progress:

```bash
tail -40 data/research/hilega-installed-e2e-validation-v1.log
```

When complete:

```bash
cat data/research/hilega-installed-e2e-validation-v1/summary.md
```

Use a fresh output directory for any rerun. No foreground 'exit code: 0' follows
nohup; Overall: PASS in summary.md and status: PASS in report.json indicate result.
The runner may wait up to five minutes for a real future five-minute boundary,
plus process/heartbeat checks. It prints progress every ten seconds during the
boundary wait. There is no patched clock or backdated Resume.

## Coverage

Unfunded Resume rejected through actual CLI/API; funding does not arm; reader cash
refresh; fresh journal BUY and reservation; CLI Pause retained established exposure;
journal EXIT while paused sells and releases; repeated polls do not duplicate;
reader restart preserves cursor; cash expiry blocks Resume; cash recovery stays
paused; killed reader automatically paused by API background monitor (no direct
watchdog call by test driver); CLI Pause visible in UI status; API restart stays
paused and old-version CLI Resume is rejected.

The final state is isolated reader stopped, API stopped, simulator paused and flat,
reservation released. All children created by this run are stopped on normal error
cleanup. An abrupt kill of the validation driver itself can leave its own isolated
children alive; inspect only the PIDs/logs under this output, never kill workers by
broad name matching. Each output preserves private logs and scenario evidence.

## Limits

No browser click/render automation; checks the UI's authenticated API contract.
Minimal API shell uses actual workspace lifespan, not the full application routes.
No actual market data, options execution, real cash accounting, external exits or
production permission. Same-boundary synthetic entry/exit is a transport lifecycle
check, not a strategy performance claim. Single simulated leg only.
Authoring checks were Python AST parsing only. Run all tests and processes on VM.
