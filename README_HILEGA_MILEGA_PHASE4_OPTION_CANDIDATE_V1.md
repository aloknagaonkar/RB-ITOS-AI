# Hilega-Milega Phase 4 — Option Candidate Observation V1

Phase 4 advances the architecture from **strategy signal** to **option-selection evidence**, without inventing a final contract-selection rule and without creating paper/live orders.

## Frozen strategy
No Hilega-Milega entry or exit rule changes. Route A, Route B, immediate RSI-down-WMA exit and the 14:55 hard cutoff stay unchanged.

## What Phase 4 adds
On every bullish Hilega entry, the live shadow can build an exact CE candidate set around signal-time ATM:

- signal spot = completed NIFTY 5m signal close
- exact half-up ATM on 50-point strike step
- CE only (bullish strategy)
- ATM ±2 strikes by default
- explicit expiry only, configured with `HILEGA_MILEGA_OPTION_EXPIRY=YYYY-MM-DD`
- exact contract identity required
- no nearest-contract fallback
- no interpolation / synthetic contract
- no premium target yet
- no selected instrument yet
- no quantity
- no paper/live order

Audit stage: `OPTION_CANDIDATE_SET`.

The payload records candidate strikes/instrument keys, expiry, ATM, signal spot, and explicitly records `selection_policy=UNDECIDED_CANDIDATE_SET_ONLY`, `selected_instrument_key=null`, `order_created=false`.

## Why expiry is explicit
The current strategy research has not yet frozen an automatic expiry-selection policy. Phase 4 therefore refuses to invent one. If `HILEGA_MILEGA_OPTION_EXPIRY` is absent, the entry is still valid but the audit records `OPTION_CANDIDATE_SET / NOT_CONFIGURED`.

## Audit clarity improvement
`STRATEGY_DECISION_RESULT` now includes `selected_route`. If Route A wins priority while Route B conditions are also true, the audit additionally records `route_b_suppressed_by_route_a_priority=true`. This changes reporting only, not strategy behavior.

## Safety
`observation_only=true`, `execution_enabled=false`, `paper_order_enabled=false`. Phase 4 creates no broker or paper order.
