# Hilega Directional Metrics Instrumentation Fix v1

This patch changes reporting only. Strategy rules and coordinator behavior remain unchanged.

Changes:
- `same_candle_reversal_blocks` increments only when an opposite entry was actually emitted and suppressed on the same exit candle.
- Exit candles with no opposite entry use `NO_SAME_CANDLE_*_ENTRY` notes.
- Ambiguous armed counters are renamed:
  - `bullish_armed_candles_while_bearish_active`
  - `bearish_armed_candles_while_bullish_active`
- Adds separate accepted arm-event counters:
  - `bullish_arm_events_while_bearish_active`
  - `bearish_arm_events_while_bullish_active`
- Whipsaw mitigation remains DEFERRED.

Validation against the current source snapshot:
`36 passed`
across bullish, bearish, bearish replay, directional coordinator, and combined directional replay tests.

No API/worker restart is required.
