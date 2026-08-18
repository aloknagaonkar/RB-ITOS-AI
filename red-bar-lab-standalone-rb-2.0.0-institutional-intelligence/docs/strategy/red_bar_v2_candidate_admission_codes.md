# Red Bar V2 Candidate Admission Codes

These codes explain why Red Bar V2 allowed, blocked, delayed, or classified a trade candidate. They do not control trade exits; the existing exit policy remains responsible for closing active trades.

## Standard decision fields

Each decision should expose:

```json
{
  "candidate_allowed": false,
  "admission_code": "REFERENCE_NOT_READY",
  "admission_reason": "The NEXT_RED_CANDLE reference has not been established.",
  "direction": null,
  "option_side": null,
  "entry_type": null,
  "trend_strength": null,
  "active_trade_count": 0,
  "previous_trade_status": null,
  "conditions": {}
}
```

Recommended fields:

- `candidate_allowed`
- `admission_code`
- `admission_reason`
- `direction`
- `option_side`
- `entry_type`
- `trend_strength`
- `reference_timestamp`
- `context_timestamp`
- `active_trade_count`
- `previous_trade_status`
- `reversal_event_id`
- `conditions`

## Code definitions

### `REFERENCE_NOT_READY`

The first completed 5-minute candle was ignored, but the first later red 5-minute candle has not yet established `NEXT_RED_CANDLE` and its midpoint.

```text
candidate_allowed = false
```

### `INITIAL_BULLISH_ALIGNMENT`

A completed 1-minute candle has full bullish initial alignment:

```text
close > midpoint
AND close > VWAP
AND RSI > 55
AND no active trade
```

```text
candidate_allowed = true
direction = BULLISH
option_side = CE
entry_type = INITIAL
trend_strength = CONFIRMED
```

### `INITIAL_BEARISH_ALIGNMENT`

A completed 1-minute candle has full bearish initial alignment:

```text
close < midpoint
AND close < VWAP
AND RSI < 45
AND no active trade
```

```text
candidate_allowed = true
direction = BEARISH
option_side = PE
entry_type = INITIAL
trend_strength = CONFIRMED
```

### `REVERSAL_CONTEXT_ALIGNED_FLAT`

The opposite-direction 5-minute RSI/VWAP reversal is aligned and there is no active trade. This works whether the exit happened before or after reversal detection.

Bullish:

```text
5m close > 5m VWAP
AND 5m RSI > 55
AND active_trade_count = 0
```

Bearish:

```text
5m close < 5m VWAP
AND 5m RSI < 45
AND active_trade_count = 0
```

When midpoint is not yet aligned:

```text
candidate_allowed = true
entry_type = REVERSAL
trend_strength = PROVISIONAL
```

### `FULL_DIRECTIONAL_ALIGNMENT`

RSI, VWAP, and the fixed Red Bar midpoint all align in one direction.

Bullish:

```text
price > VWAP
AND RSI > 55
AND price > midpoint
```

Bearish:

```text
price < VWAP
AND RSI < 45
AND price < midpoint
```

When flat, a confirmed candidate may be admitted. If a provisional reversal trade already exists, this is only a state upgrade and must not create a duplicate candidate.

### `ACTIVE_TRADE_BLOCK`

A valid directional or reversal condition exists, but a trade is still active.

```text
candidate_allowed = false
```

Example: bullish reversal detected while a PE position remains active.

### `PREVIOUS_TRADE_NOT_CLOSED`

The prior trade is in `ACTIVE`, `EXIT_SIGNALLED`, or `EXIT_PENDING`, but not terminal `CLOSED` state.

```text
candidate_allowed = false
```

Difference:

- `ACTIVE_TRADE_BLOCK` is the broad overlapping-position gate.
- `PREVIOUS_TRADE_NOT_CLOSED` explains that a valid opposite reversal is specifically waiting for the previous position to finish closing.

### `RSI_NOT_ALIGNED`

The required RSI threshold is not satisfied.

```text
bullish failure: RSI <= 55
bearish failure: RSI >= 45
candidate_allowed = false
```

### `VWAP_NOT_ALIGNED`

The completed candle has not closed on the required side of VWAP.

```text
bullish failure: close <= VWAP
bearish failure: close >= VWAP
candidate_allowed = false
```

### `MIDPOINT_NOT_ALIGNED`

RSI and VWAP support the direction, but price has not aligned with the fixed midpoint.

For reversal entries:

```text
candidate_allowed = true
trend_strength = PROVISIONAL
```

For normal initial entries, midpoint alignment is mandatory:

```text
candidate_allowed = false
```

This code may therefore be stored as both a classification detail and a primary blocking reason, depending on entry type.

### `CONTEXT_STALE`

The RSI/VWAP snapshot is missing, old, based on an incomplete candle, or does not match the evaluated candle timestamp.

```text
candidate_allowed = false
```

Required alignment:

```text
initial entry: close, RSI, and VWAP from the same completed 1m candle
reversal: close, RSI, and VWAP from the same completed 5m candle
```

### `DUPLICATE_SIGNAL`

An identical candidate identity has already been processed.

Recommended identity:

```text
session_date
+ strategy_version
+ direction
+ event_type
+ context_candle_timestamp
+ reference_timestamp
```

```text
candidate_allowed = false
```

### `REVERSAL_ALREADY_CONSUMED`

The same reversal event has already generated an opposite-side candidate or trade. Continued RSI/VWAP alignment must not repeatedly create entries.

```text
candidate_allowed = false
```

Each reversal receives a deterministic `reversal_event_id`; after candidate creation it is marked consumed.

## Primary-code priority

When multiple conditions apply, select the primary code in this order and retain every detailed condition in `conditions`:

```text
1. REFERENCE_NOT_READY
2. CONTEXT_STALE
3. DUPLICATE_SIGNAL
4. REVERSAL_ALREADY_CONSUMED
5. ACTIVE_TRADE_BLOCK
6. PREVIOUS_TRADE_NOT_CLOSED
7. RSI_NOT_ALIGNED
8. VWAP_NOT_ALIGNED
9. MIDPOINT_NOT_ALIGNED
10. INITIAL_BULLISH_ALIGNMENT / INITIAL_BEARISH_ALIGNMENT
11. REVERSAL_CONTEXT_ALIGNED_FLAT
12. FULL_DIRECTIONAL_ALIGNMENT
```

## Example allowed reversal decision

```json
{
  "candidate_allowed": true,
  "admission_code": "REVERSAL_CONTEXT_ALIGNED_FLAT",
  "admission_reason": "Bullish RSI/VWAP reversal is aligned, the previous PE trade is closed, and no trade is active.",
  "strategy": "RED_BAR_V2",
  "direction": "BULLISH",
  "option_side": "CE",
  "entry_type": "REVERSAL",
  "trend_strength": "PROVISIONAL",
  "previous_trade_status": "CLOSED",
  "active_trade_count": 0,
  "conditions": {
    "rsi_aligned": true,
    "vwap_aligned": true,
    "midpoint_aligned": false,
    "context_fresh": true,
    "duplicate_signal": false,
    "reversal_already_consumed": false
  }
}
```

## Architecture usage

The same codes must be used by:

- historical replay;
- legacy paper runtime;
- independent strategy worker;
- New Paper Trading UI;
- parity diagnostics;
- CSV exports.

The flow remains:

```text
Red Bar V2 directional state
→ candidate admission decision
→ candidate builder
→ committee / risk / capital gates
→ paper or live execution
```
