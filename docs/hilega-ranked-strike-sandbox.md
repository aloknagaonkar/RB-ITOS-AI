# HILEGA strike quality: research, observation, then Sandbox

This update changes code only. It contains no approved policy, environment changes,
orders, strategy timing changes, or session-end extension. The default remains
FIVE_ACTUAL_SANDBOX_LEGS. The 14:55 cutoff is unchanged. Live execution is disabled.
No tests, application Python, or frontend build were run locally.

## Modes and activation

- FIVE_ACTUAL_SANDBOX_LEGS: existing five nearest-expiry ATM ±2 candidates.
- RANKED_OBSERVATION_ONLY: display fixed role priorities and timestamped quote
  eligibility; submit no entries. Later exits are harmless no-position records.
  It replaces entry execution for that armed session, rather than adding orders
  alongside the five-leg session.
- RANKED_ONE_LEG_SANDBOX: one eligible role from an explicitly approved policy.
  Contract identity, quantity and selector evidence are durable before submission.

No mode is activated by installing this update. Do not edit the mode while trading.
If it changes, new entries are declined while already-known exits use the saved
contract/quantity. The worker does not use the new mode until a clean new arm.

Observation policies may contain approved:false; this never permits ranked
execution. Both modes need a versioned file matching the actual running strategy.
Example JSON shape, with arbitrary demonstration thresholds and priorities:

```json
{
  "version": "observation-example-v1",
  "strategy_version": "five-minute-setup-1.2.0-pending-switch",
  "approved": false,
  "ranked_ce_roles": [0, -1, 1, -2, 2],
  "ranked_pe_roles": [0, 1, -1, 2, -2],
  "max_spread_pct": 5,
  "min_bid_quantity": 65,
  "min_ask_quantity": 65,
  "min_volume": 100,
  "max_signal_age_seconds": 120,
  "max_quote_age_seconds": 30,
  "max_one_lot_premium_rupees": 10000
}
```

These values are not research recommendations. No example policy is installed.
The policy hash is frozen when arming. Changed policy files cannot create a new
entry; existing position exits remain independent of policy loading.

Observation requires HILEGA_STRIKE_SELECTOR_MODE=RANKED_OBSERVATION_ONLY and
HILEGA_STRIKE_POLICY_PATH to point to the observation policy, followed by a clean
arm with --confirm ARM_UPSTOX_SANDBOX_RANKING_OBSERVATION. Ranked execution instead
requires approved:true and --confirm ARM_UPSTOX_SANDBOX_ONE_RANKED_LEG. Retain the
existing ARM_UPSTOX_SANDBOX_FIVE_LEGS confirmation for the default mode.
The existing worker auto-arm honors the chosen mode for future clean sessions.
There is no cron added. Activation requires a separate operator decision.

HILEGA_PENDING_OPPOSITE_SWITCH_ENABLED=1 must be in the process environment for
both arming and worker startup if using the pending-switch strategy. The replay
module reads it at import time; .env alone does not establish that rules version.

## Automatic fills and migration

Newly armed sessions record automatic_fill_ledger_version=HILEGA_SANDBOX_FILL_LEDGER_V1.
Existing already-armed sessions and old untagged ACK journals keep their original
semantics; do not interpret that history as confirmed fills. Upgrade/re-arm only
while flat with no uncertain requests or pending fill orders. Newly auto-armed
sessions also get the ledger; verify on the VM before restarting that worker.

The automatic ledger uses the same order identity/quantity checks as manual exit.
BUY acknowledgments await order details. Pending orders are polled and receive a
single durable cancel request after 60 seconds, or immediately on an exit while a
BUY is pending. Cancellation ACKs do not prove cancellation. Residual SELLs use
only the confirmed BUY fill less all confirmed SELL fills. A rejected or partial
SELL can be retried after terminal evidence, at most three submitted attempts.
No unknown order request is blindly replayed; deterministic-tag lookup is required.
Missing details, mismatched identity, regressed fills, and exhausted retries require
reconciliation. A lost cancel response may need operator action; it is not retried
blindly. These behaviors still need VM and broker validation.

Dashboard quantities distinguish requested, filled and remaining. Fully closed
ledger trades use confirmed average prices and gross realized P&L. Open P&L also
uses current quote estimates. Neither view deducts fees. Historical ACK trades
remain estimated. Automatic fill evidence is journaled; timestamps displayed for
order submission are not exchange execution timestamps. Manual exit remains the
existing fill-aware cancellation/flattening workflow and strategy reset handshake.

## Research inputs and coverage

The report reads accepted alignment replay trades, never order ACKs, and uses their
confirmed entry and exit times. The default pricing lag is one minute; repeat with
lag zero as a separate sensitivity scenario. Candle OPEN prices are not executable
bid/ask fills. No code learns or approves a policy automatically.

Each accepted trade contributes five expected rows even if cache or contracts are
missing. Summaries provide overall exact coverage and a common-five-contract
cohort for fair role comparisons, with gross outcome, scenario net rupees, returns,
MAE and MFE. Missing replay dates are not included in trade coverage, so the report
does not claim exchange-calendar completeness. Existing train/validation dates
have already been examined in earlier research; they are not a fresh untouched
holdout. Freeze any policy from training only and use future untouched sessions
for further validation.

Historical contract metadata must prove the nearest eligible expiry, historical
lot size and exact five instrument keys. Do not infer these from the largest cache.
Use --contract-manifest with this shape (example identities omitted deliberately):

```
{
  "YYYY-MM-DD": {
    "1": {
      "strategy_entry_time": "accepted replay entry timestamp",
      "expiry": "verified nearest expiry",
      "nearest_expiry_verified": true,
      "atm": 22500,
      "strike_interval": 50,
      "contracts": [five objects with role, option_type, expiry, strike,
                    instrument_key and historical integer lot_size]
    }
  }
}
```

The per-day key "1" is the one-based replay trade index. Freeze this from historical
contract evidence, not from subsequent winning option paths. ATM uses confirmed
entry spot with ties choosing the lower strike, matching the worker's tie rule.
The worker still takes a current spot at dispatch; a delayed dispatch can change
ATM, so this research universe is explicitly an entry-time universe. For forward
validation compare against the actual recorded selection candidates and delay.
Without a manifest, the script is useful only as a replay inventory: all contract
rows are incomplete and no ranking can be inferred. No synthetic contracts or
missing-minute interpolation are used.

Supply round-trip costs in rupees per one-lot trade (all fee/tax costs you intend to
model) and option-point slippage per side. These are declared scenario assumptions,
not an accurate broker tariff calculation. Run multiple realistic assumptions.
For a gross-only coverage diagnostic, explicitly supply zeros:

```bash
PYTHONPATH=backend:. .venv/bin/python scripts/research_hilega_strike_ranking.py \
  --expected-version five-minute-setup-1.2.0-pending-switch \
  --round-trip-cost-rupees 0 --slippage-points-per-side 0 \
  > /tmp/hilega-strike-coverage.json
```

After the historical manifest is ready, add --contract-manifest /path/to/manifest.json
and replace zeros with your chosen nonzero cost/slippage scenario. Review CE and PE
coverage separately and compare only common-cohort results. Do not approve a policy
based only on profitable cache subsets.

## Manual reset bridge

The bridge replays causal source order and applies only verified manual resets:
matching request, strategy, session, completion timestamp, durable reset acknowledgment,
and closed trade identities. A reset removes only those trade IDs. Existing blocked
intents remain immutable and are never converted into executable orders. This
repair permits a later fresh signal; it does not resurrect the blocked 14:52 trade.

## VM checks

The update package README provides installation, tests, build and restart commands.
Tests are authored but have not been executed locally. Verify fill parsing against
actual Sandbox responses, including zero and partial fills, before treating this
path as reliable. Live execution still requires separate authorization and further
end-to-end validation; this package cannot activate live execution.
