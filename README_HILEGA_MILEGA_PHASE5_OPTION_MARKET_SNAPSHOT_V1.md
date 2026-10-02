# Hilega-Milega Phase 5 — Exact Option Candidate Market Snapshot V1

Phase 5 is observation-only. It does not change Hilega-Milega entry/exit logic, does not select an option contract, does not size quantity, and does not create paper/live orders.

## Purpose

After a fresh bullish entry creates the exact CE ATM±2 candidate set, capture the exact last fully completed 1-minute option candle for every candidate at the strategy signal boundary.

For a 5-minute signal candle labelled `09:55`, the causal decision boundary is `10:00`. Upstox 1-minute candles are start-labelled, therefore the exact final completed minute is `09:59`.

No nearest-minute fallback, interpolation, or synthetic quote is allowed. If any candidate lacks the exact minute, the snapshot is `INCOMPLETE`.

## New audit stage

`OPTION_CANDIDATE_MARKET_SNAPSHOT`

It records candidate strike/instrument, exact minute timestamp, OHLC, volume, snapshot semantics, and safety flags. `selected_instrument_key` remains null and `order_created` remains false.

## Still frozen

- Route A / Route B logic
- opening path
- immediate RSI↓WMA structural exit
- 14:55 cutoff
- option selection policy remains undecided
- no risk sizing
- no orders

## Live validation reminders still open

- naturally occurring Route B live event
- 14:55 cutoff at exact 14:55 open
- first fresh Phase 5 entry should produce both `OPTION_CANDIDATE_SET` and `OPTION_CANDIDATE_MARKET_SNAPSHOT`
