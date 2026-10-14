# Enable historical alignment + dual-exit

Strategy ID: HILEGA_V2_ALIGNMENT_DUAL_EXIT.
Live adapter shares the existing historical canonical setup, minute confirmation gate and dual-exit functions. Historical engine is unchanged.

POLICY: canonical setup OR existing alternative completed-five-minute RSI9/EMA3(RSI)/WMA21(RSI) alignment with positive expanding minute gap. Historical minute confirmation retains strength >=0.75, adjacent-minute persistence, positive expanding gap, later arm confirmation and ten-minute window. This is the requested historical version, not strict-five-minute-only research. Completed-five-minute exit requires BOTH RSI9 and EMA3 across WMA21 against the position. Canonical exit cancels pending setup but does not close the actual independent position. Existing same-boundary replacement conditions apply, EXIT before ENTRY; existing 14:55 cutoff closes actual ownership and next session resets. No Midpoint filter or EMA10 exit.

Five actual Sandbox legs, sizing, automatic expiry, journal, P&L, PCR and Midpoint behaviour remain intact. Activation does not submit previous entries retrospectively. Broker acceptance does not prove an exchange fill.

Extract ZIP into ~/RB-ITOS-AI then run:

```bash
cd ~/RB-ITOS-AI
source .venv/bin/activate
unset LIVE_SHADOW_STRATEGY
./scripts/stop_hilega_upstox_sandbox_worker.sh
python hilega_alignment_dual_exit_live_bundle/install.py &&
python hilega_alignment_dual_exit_live_bundle/activate.py --session 2026-10-12 &&
./scripts/restart.sh &&
./scripts/start_hilega_upstox_sandbox_worker.sh &&
./scripts/status_hilega_upstox_sandbox_worker.sh
```

Installer guards original repository hashes and historical dependency, runs tests/build and restores source/frontend output on failure. No selection change, broker call or order occurs during installation. Activation changes only LIVE_SHADOW_STRATEGY in .env and uses existing local Sandbox arm with fresh baseline. It requires existing ready Sandbox config and rejects open/uncertain exposure, conflicting exported selection or invalid local warm-up data before mutation. Arm is session-specific. Live execution remains disabled.

If WARMUP_CACHE_INVALID appears, recover the named cache's missing evidence through the existing recovery workflow. Do not fabricate candles or omit a trading day. The strategy selection and arm remain unchanged on this failure.

Optional exact offline VM parity check:
```bash
PYTHONPATH=backend:. python scripts/validate_hilega_alignment_live_parity.py --dates 2026-10-06 2026-10-07 2026-10-08 2026-10-09
```
It checks trades, times/prices/points, setups and minute gate checks with mocked option hooks; no broker access. Uses historical replay's cache roots.

After restart, check fast directional status and Sandbox status both show HILEGA_V2_ALIGNMENT_DUAL_EXIT. Sandbox should show intended session, armed=true, kill_switch=false, FIVE_ACTUAL_SANDBOX_LEGS, live_execution_enabled=false. Confirm fresh eligible signals populate five legs and existing P&L/exit records during the session.

VALIDATION: 33 selected tests, Python compilation and TypeScript/Vite build passed. Real-candle live/historical parity passed March 27 (6 trades, -121.75), March 30 (5, -204.60), October 6 (7, -50.70), October 7 (4, +49.90), October 8 (6, -58.80). Values are Nifty points. October 9 validation blocked by incomplete prior warm-up candle 15:05 missing 15:09. Two older saved-artifact tests fail because they expect loading without source caches, conflicting with the supplied historical engine's existing validation. Engine unchanged; full repository tests not run. No VM activation or actual broker fills validated here.

ROLLBACK: stop Sandbox first. Matching source backups are under data/backups/hilega-alignment-live-* including frontend-dist. Matching activation backups are under data/backups/hilega-alignment-activation-* (env.before, control.before.json). Restore matching files and restart. Do not overwrite a journal with open/uncertain exposure or replay old entries to recreate positions.
