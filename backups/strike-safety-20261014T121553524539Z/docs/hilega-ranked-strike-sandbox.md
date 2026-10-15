# HILEGA ranked strike selection in Upstox Sandbox

The default remains `FIVE_ACTUAL_SANDBOX_LEGS`. The optional `RANKED_ONE_LEG_SANDBOX` mode selects one contract from the five nearest-expiry NIFTY strikes (ATM ±2). Bullish entries buy CE; bearish entries buy PE. The selected contract is frozen in the basket journal before an order request, and its exit uses the same contract. This mode cannot send live orders.

## Research before choosing a policy

On the VM, use previously generated `HILEGA_V2_ALIGNMENT_DUAL_EXIT_REPLAY_V1` day files and cached historical option OHLC. From the repo root, with the backend on `PYTHONPATH`:

```bash
PYTHONPATH=backend python scripts/research_hilega_strike_ranking.py \
  --expected-version five-minute-setup-1.2.0-pending-switch \
  > /tmp/hilega-strike-comparison.json
```

The report shows each CE and PE role for each accepted replay trade, exact contract and minute coverage, train/validation summaries, and paired gross option points versus ATM. It uses the underlying replay's entry and exit times and option minute opens one minute later by default. Missing contracts, missing minutes, and ambiguous identities are marked incomplete. The price proxy excludes executable spread, slippage, fees, and broker fills. A profitable rank cannot be inferred from this report unless coverage is adequate for both CE and PE on held-out dates and survives realistic costs. The script does not approve a policy or place orders.

## Policy and activation

After reviewing the report, create an approved JSON policy outside version control. Example shape only; the rank order and limits below are **not researched recommendations**:

```json
{
  "version": "operator-reviewed-v1",
  "strategy_version": "five-minute-setup-1.2.0-pending-switch",
  "approved": true,
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

Set `HILEGA_STRIKE_SELECTOR_MODE=RANKED_ONE_LEG_SANDBOX` and `HILEGA_STRIKE_POLICY_PATH` to that file. Arm a new session with `--confirm ARM_UPSTOX_SANDBOX_ONE_RANKED_LEG` using the existing basket worker command. Arming requires no open or uncertain Sandbox legs. The policy must match the running strategy rules version; its content hash and version are recorded in control state. A mode change after arming blocks processing. The default five-leg mode retains its existing arming token.

At entry, the worker checks the signal age and full quote timestamp, bid/ask spread, top-of-book depth, volume, and one-lot premium. It takes the first eligible role in the approved CE or PE list. A missing, stale, or unsuitable quote results in `ENTRY_NOT_TRADED`; the eventual strategy exit records `EXIT_NO_POSITION`. The journal stores all candidate evidence and the chosen contract. The dashboard shows the policy decision and one-leg trade.

## Operational limits

This is Sandbox order execution only. The automatic basket path still treats an accepted order acknowledgment as an open or closed leg; it does not reconcile fills and partial fills before the next automatic order. The dashboard labels those values as estimates. Check order details and reconcile any uncertain, rejected, unfilled, or partial order before relying on its position or P&L. Do not use this path for live execution without fill-aware accounting and separate live authorization.

Manual exit reset now writes a bridge state reset only after matching the processed strategy reset audit, the manual-exit request in `READY_FOR_FRESH_SIGNAL`, and the durable reset acknowledgment. The reset permits a later fresh strategy entry in bridge state; it does not recreate an earlier blocked signal.
