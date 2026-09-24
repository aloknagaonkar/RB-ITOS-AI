# Hilega Directional Phase D2 — Combined Historical Replay

Adds combined bullish+bearish historical replay through `HilegaDirectionalCoordinatorV1`.

Per-session outputs:
- `directional-candle-by-candle.csv/json`
- `directional-events.csv/json`
- `directional-trades.csv`
- `directional-manual-validation.txt`

Multi-session outputs:
- `multi-session-directional-summary.json`
- `multi-session-directional-sessions.csv`
- `multi-session-directional-trades.csv`
- `multi-session-directional-events.csv`
- `multi-session-directional-candle-by-candle.csv`

The replay records:
- active owner before/after each candle
- bullish and bearish internal states
- informational ARMED states
- accepted events
- suppressed opposite-side entries
- same-candle reversal blocking notes
- direction-aware Nifty points

Whipsaw mitigation remains explicitly DEFERRED.

Validation against the current source snapshot:
`32 passed`
across bullish, bearish, bearish replay, coordinator, and combined directional replay tests.

No API/worker restart is required.
