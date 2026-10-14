# Top-five strike observation dashboard and per-strike audit

Replaces only the visible “Skipped, blocked and reconciliation events” JSON panel.
Existing execution journal records, five-leg trading and the 14:55 cutoff are unchanged.
No selector, broker connection, observation collector or trading worker is started by this package.
The panel displays NOT_CONNECTED until a separate collector writes valid frames.

From the repository root on the VM:

```bash
python hilega_strike_observation_ui_update/install.py --check
PYTHONPATH=backend:. .venv/bin/python -m pytest -q hilega_strike_observation_ui_update/tests
python hilega_strike_observation_ui_update/install.py
npm --prefix frontend run build
bash scripts/restart_api_only.sh
```

No local tests or frontend build have been run. The guarded installer refuses an
unrecognized source file and backs up changed files. No Sandbox worker restart is required.

## Collector contract for the next integration

Append newline-terminated self-contained JSON frames to
`data/live-observation/hilega-strike-observation-v1/shadow_strike_obs.jsonl`.
Model must be `HILEGA_STRIKE_OBSERVATION_FRAME_V1`. Each frame is a recorded
evaluation/update, not a trade order. The endpoint reads at most the final 2 MiB
and 50 complete lines. History shown is bounded and excludes incomplete writes.

Frame fields: `observation_id`, `entry_snapshot_id`, `timestamp`, `entry_timestamp`,
`signal`, `spot`, `policy_version`, `verdict`, `reason`, `max_quote_age_seconds`,
`assumptions`, `top5`, `rejections`, `unfilled_slot_reason`.

`top5` is ordered by the policy at entry, with at most five distinct instrument
keys. Never re-rank or replace these frozen contracts on mark/exit updates.
Each row records `instrument_key`, `strike`, `option_type`, `quantity`,
`entry_bid`, `entry_ask`, `entry_quote_timestamp`, `entry_bid_quantity`,
`entry_ask_quantity`, `entry_spread_percent`, `delta`, `gamma`, `theta`, `vega`,
`iv`, `dte`, `modelled_roi_percent`, `leverage_score`, `delta_target_distance`,
`invalidation_modelled_premium`, `invalidation_modelled_change`, and `audit`.

Audit fields: `selection_reason`, `favourable_conditions` (strings), `filters`
(`name`, `observed`, `required`, `result`), `rank_comparison`, `risk_flags`.
Capture these from the evaluator's actual entry evidence, never compose them
retroactively from later prices. Record thresholds, Greek units, move, holding
time, IV shift, cost assumptions and invalidation spot in `assumptions`.
Rejections contain `strike`, `option_type`, `step`, `reasons`.

Hypothetical tracking adds `state`, `current_bid`, `quote_timestamp`, `exit_bid`,
`exit_quote_timestamp`, `price_evidence_source`, `total_cost_rupees`. Only
MARKET_UPDATE or RECORDED_FEED_UPDATE evidence is accepted for P&L. A response
timestamp alone is insufficient. Costs are explicit total round-trip rupees for
the observed quantity; missing costs do not default to zero. Per row:
`points = bid - entry_ask`; `net_rupees = points * quantity - total_cost_rupees`;
`net_roi = net_rupees / (entry_ask * quantity) * 100`.
These are hypothetical quote outcomes, not executable fills. Stale open bids,
future timestamps, missing prices or unverified evidence produce unavailable P&L.
Captured historical exit quotes are allowed for CLOSED observations.

This package renders evidence and does not validate or implement the ranking
policy. A separate collector/evaluator integration is still required before
automatic signal snapshots, top-five audits and mark/exit updates appear.

The observation section is positioned directly after Current active Sandbox trade,
before Completed Sandbox trades. This installer also accepts the previous UI package.

## Replacement of earlier fixed-priority ranking

The earlier “Strike ranking and no-trade decisions” section is removed. There
is one ranking section, below the active Sandbox trade, using the new observer
journal. Fixed-priority execution code and stored decisions remain intact for
existing Sandbox behavior and audit history. No trading selector is activated.

Use the separately provided hilega-shadow-observer.zip for the policy evaluator
and its VM tests. Its independent feed publisher and configured assumptions are
still required. The existing accepted HILEGA signal alone does not prove the
required breakout-velocity context. This UI update does not invent that flag.

Completed Sandbox trades now use native, keyboard-accessible details/summary
expanders, initially closed. The existing header, status, contract count and
P&L remain visible. Active trade rows remain expanded. No accounting changes.
