# Hilega-Milega Phase 7B — Historical/Live Functional Parity + Canonical Audit V1

## Goal
Historical replay and live shadow must share trading semantics. The only permitted differences are the market-data source, clock/restart behavior and runtime metadata.

## Added
- `hilega_milega_functional_parity_replay_v1.py`: drives the **same live coordinator** with historical underlying/options and a simulated IST clock. No strategy, candidate, lifecycle or exit logic is reimplemented.
- `hilega_milega_audit_report_v1.py`: one canonical detailed-audit projector for historical and live step-audit rows.
- Live API endpoints `/audit-index` and `/audit-detail?checkpoint=...` for UI Audit drill-down.
- Existing historical replay now writes `detailed-audit-report.json` using the same canonical projector.

## Functional parity contract
Same market data must imply the same:
- 5m candles and RSI/EMA/WMA values
- Opening / Route A / Route B decisions and state transitions
- structural exit and 14:55 cutoff semantics
- expiry, ATM±2 CE candidate set and exact instrument identity
- exact option entry timing, lifecycle updates, MFE/MAE and exit timing
- decision/rejection reasons and audit vocabulary

Runtime-only differences such as bootstrap events, wall-clock event time, hashes and process identity are excluded from semantic parity comparisons.

## Audit drill-down
The canonical report includes strategy state, bar, current/previous indicators, condition table, Route A/B pass/fail reasons, selected route/priority suppression, transitions, option candidate/snapshot, ATM±2 lifecycle, exit details, safety flags and hash-chain integrity.

## Safety
Observation only. Execution disabled. Paper orders disabled. Quantity remains unset. No nearest strike/minute fallback or interpolation.

## Validation performed in bundle workspace
Backend/relevant suite: **42 passed**.
Python compile validation: PASS.
Frontend source was wired to a new **Hilega shadow** tab with an **Audit** button and canonical detailed report view. A Vite/TypeScript production build could not be executed in the isolated bundle workspace because `frontend/node_modules` was not present; run `npm ci` (if needed) and `npm run build` in the real repo before deployment.

## Updated checklist after Phase 7B
### Implemented / tested
- same canonical Hilega strategy for historical and live
- historical functional-parity adapter drives the same live coordinator with a simulated clock
- same ATM±2 candidate/lifecycle semantics available to parity replay
- one canonical detailed-audit report schema
- existing historical replay writes `detailed-audit-report.json`
- live API exposes `/audit-index` and `/audit-detail`
- Hilega UI tab has an Audit drill-down button
- audit includes current/previous indicators, Route A/B reasons, route priority, transitions, option candidate/snapshot/lifecycle, safety and hash-chain metadata

### Still required before claiming full production parity
- run a recorded real session through historical parity replay and live-shadow simulation and diff normalized semantic event streams
- validate corrected-expiry candidate/snapshot/lifecycle on a fresh live signal
- validate genuine Route B live event
- validate natural 14:55 underlying + ATM±2 option exit
- add automatic expiry resolver
- persist canonical shadow trade ledger
- deferred historical ATM±2 performance comparison
