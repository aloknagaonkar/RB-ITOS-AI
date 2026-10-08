# Sandbox pre-arm exit recovery

The shadow trade entered before Sandbox arming was excluded correctly. Its later exit incorrectly stopped the Sandbox worker with UNMATCHED_EXIT_BLOCKED.

This patch skips an exit only when exactly one matching ENTRY intent exists at or before the arm baseline, both events belong to the armed date and direction, and no dispatch attempt exists for that trade. It journals SKIPPED_PRE_ARM_TRADE_EXIT once without a broker call. Missing proof, post-arm entries and prior attempted dispatches retain the mismatch stop. Future eligible entries and exits continue normally.

If the expiry workspace component is installed, its arm row shows the failure reason/time and distinguishes missing state from Disarmed / kill switch ON.

From the repository root, after extracting this ZIP:

```bash
./scripts/stop_hilega_upstox_sandbox_worker.sh
python hilega_sandbox_prearm_exit_fix_bundle/install.py
```

Only after PASS, re-arm for the intended IST session and start:

```bash
PYTHONPATH=backend:. python -m market_lab.hilega_upstox_sandbox_live_worker_v1 \
  --arm-session 2026-10-08 --max-orders 4 --confirm ARM_UPSTOX_SANDBOX_ONLY
./scripts/start_hilega_upstox_sandbox_worker.sh
./scripts/status_hilega_upstox_sandbox_worker.sh
```

Use the current session date if installing later. Re-arming advances the baseline; earlier entries are not replayed. An existing active shadow trade is not adopted as a Sandbox position. Its subsequent exit will be skipped if proof is available. New post-arm entries are eligible.

The installer creates backups, runs worker/bridge/execution regression tests and builds the frontend if the workspace component exists. On failure it restores source. It does not change control files, strategy rules, audit history, tokens or send orders. Refresh the UI after successful build. No core service restart is needed for this worker-only backend change.

Inspect data/live-observation/hilega-upstox-sandbox-v1/live-dispatch.jsonl for the skip and subsequent accepted orders. ACCEPTED is submission acknowledgement, not proof of a broker fill or realized P&L.
