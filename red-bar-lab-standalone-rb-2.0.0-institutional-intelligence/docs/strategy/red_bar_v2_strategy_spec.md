# Red Bar V2 Strategy Specification

## Status

- Branch: `feat/red-bar-v2-rsi-vwap-reversal`
- Strategy key: `RED_BAR_V2`
- Current rollout target: historical replay, then legacy paper test, then independent-worker parity, then promotion.
- Red Bar V1 remains in the repository for rollback but is disabled when V2 is selected.

## Design boundaries

Red Bar V2 owns directional signal and reversal-state detection.

It does not:

- close an active trade;
- replace the existing exit policy;
- bypass option selection, committee, portfolio, risk, capital, or execution gates;
- use incomplete candles.

The existing exit policy remains the only authority that closes active trades.

## 1. Daily reference candle

1. Ignore the first completed 5-minute candle of the session, regardless of whether it is red or green.
2. Starting with the next completed 5-minute candle, wait for the first red candle where `close < open`.
3. Lock this candle as `NEXT_RED_CANDLE` for the session.
4. Later red candles do not replace it.
5. Calculate and store:

```text
midpoint = (high + low) / 2
```

The midpoint remains the fixed structural reference for the session.

## 2. Shared market context

A shared market-context engine calculates RSI and VWAP outside the Red Bar strategy.

Required context:

- completed 1-minute candle context for initial direction;
- completed 5-minute candle context for reversal detection;
- exact candle timestamp;
- close price;
- RSI value and period;
- VWAP value;
- freshness and data-quality status.

Initial default thresholds:

```text
RSI period: 14
Bullish: RSI > 55
Bearish: RSI < 45
```

The same context implementation must be used by historical replay, legacy runtime, and the independent worker.

## 3. Initial directional signal

Evaluate every completed 1-minute candle after `NEXT_RED_CANDLE` is ready.

### Initial bullish signal

```text
1m close > NEXT_RED_CANDLE midpoint
AND
1m close > 1m VWAP
AND
1m RSI > 55
AND
no active trade exists
```

Result:

```text
direction = BULLISH
option_side = CE
entry_type = INITIAL
trend_strength = CONFIRMED
admission_code = INITIAL_BULLISH_ALIGNMENT
```

### Initial bearish signal

```text
1m close < NEXT_RED_CANDLE midpoint
AND
1m close < 1m VWAP
AND
1m RSI < 45
AND
no active trade exists
```

Result:

```text
direction = BEARISH
option_side = PE
entry_type = INITIAL
trend_strength = CONFIRMED
admission_code = INITIAL_BEARISH_ALIGNMENT
```

The alignment itself creates the signal. No extra break of the reference candle high or low is required.

## 4. Reversal monitoring

Reversal monitoring uses completed 5-minute candles.

### While a PE trade is active or after it has exited

Detect bullish reversal context when:

```text
5m close > 5m VWAP
AND
5m RSI > 55
```

Set:

```text
BULLISH_REVERSAL_DETECTED
```

### While a CE trade is active or after it has exited

Detect bearish reversal context when:

```text
5m close < 5m VWAP
AND
5m RSI < 45
```

Set:

```text
BEARISH_REVERSAL_DETECTED
```

Reversal detection does not close the current trade.

## 5. Exit-policy ordering

The system must support both valid event orders.

### Reversal detected before trade exit

```text
reversal detected
→ wait until the existing exit policy closes the active trade
→ verify actual CLOSED status
→ admit opposite candidate when no active trade remains
```

### Trade exits before reversal detection

```text
exit policy closes trade
→ remain flat
→ continue reversal monitoring
→ admit opposite candidate immediately when reversal context is later detected
```

`ACTIVE`, `EXIT_SIGNALLED`, and `EXIT_PENDING` do not count as closed.

## 6. Reversal entry strength

A reversal entry can be admitted from RSI/VWAP alignment without waiting for midpoint alignment.

### Provisional reversal

```text
opposite 5m RSI/VWAP context aligned
AND
previous trade is CLOSED
AND
active_trade_count = 0
AND
midpoint is not yet aligned
```

Result:

```text
entry_type = REVERSAL
trend_strength = PROVISIONAL
admission_code = REVERSAL_CONTEXT_ALIGNED_FLAT
```

### Confirmed reversal

```text
opposite 5m RSI/VWAP context aligned
AND
previous trade is CLOSED
AND
active_trade_count = 0
AND
price is also aligned with NEXT_RED_CANDLE midpoint
```

Result:

```text
entry_type = REVERSAL
trend_strength = CONFIRMED
admission_code = FULL_DIRECTIONAL_ALIGNMENT
```

### Later midpoint confirmation

If a provisional reversal trade is already active and price later aligns with the midpoint:

```text
PROVISIONAL_BULLISH → CONFIRMED_BULLISH
PROVISIONAL_BEARISH → CONFIRMED_BEARISH
```

This is a state upgrade only. It must not create a second candidate or trade.

## 7. Candidate admission

A new candidate requires:

```text
reference ready
AND
context fresh
AND
valid directional or reversal alignment
AND
active_trade_count = 0
AND
not a duplicate
AND
reversal event not already consumed
```

Every decision must include:

- `candidate_allowed`;
- `admission_code`;
- `admission_reason`;
- direction and option side;
- entry type;
- trend strength;
- RSI/VWAP/midpoint condition flags;
- previous trade state;
- active trade count;
- context and reference timestamps;
- deterministic event identity.

## 8. Deduplication and consumption

Use deterministic identities for context, direction events, and candidates.

Recommended signal identity components:

```text
session_date
+ strategy_version
+ direction
+ event_type
+ context_candle_timestamp
+ reference_timestamp
```

A reversal event can generate at most one opposite-side candidate. After candidate creation, mark the reversal event as consumed.

## 9. Persistence and architecture compatibility

The same shared engine and event schema must be used by:

- historical replay;
- legacy paper-trading runtime;
- independent strategy worker;
- new Paper Trading UI;
- comparison diagnostics and CSV export.

During legacy paper testing:

```text
legacy = sole candidate/order writer
independent worker = shadow-only
```

After promotion:

```text
independent worker = sole automatic writer
legacy UI = read-only
```

Existing execution and exit tables remain authoritative and are not rewritten.

## 10. Rollout gates

1. Specification frozen.
2. Shared RSI/VWAP context implemented and tested.
3. V2 reference, direction, reversal, and admission engines implemented.
4. Historical replay completed.
5. Legacy paper test completed.
6. Legacy-versus-worker parity validated.
7. Restart, stale-context, duplicate, and missed-candle tests passed.
8. Candidate persistence promoted to the independent worker.
9. Execution remains behind existing committee, risk, capital, and portfolio gates.
