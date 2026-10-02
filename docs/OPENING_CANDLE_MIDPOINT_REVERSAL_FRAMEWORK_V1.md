# Opening Candle Midpoint Reversal Framework V1

This module generalizes the midpoint research into two symmetric setup families.

## 1. Bearish breakdown -> bullish reclaim

Reference: first RED 5-minute candle after the ignored 09:15-09:19 candle.

```text
RED midpoint breaks downward
        ↓
RED low breaks
        ↓
bearish continuation research (PE side)
        OR
original midpoint reclaims upward
        ↓
bullish reclaim research (CE side)
```

## 2. Bullish breakout -> bearish reclaim

Reference: first GREEN 5-minute candle after the ignored 09:15-09:19 candle.

```text
GREEN midpoint breaks upward
        ↓
GREEN high breaks
        ↓
bullish continuation research (CE side)
        OR
original midpoint reclaims downward
        ↓
bearish reclaim research (PE side)
```

The red and green references are independent. Both may exist in one session.

## Important invariants

- The opening 09:15-09:19 5m candle is ignored.
- Once selected, the reference candle/midpoint is persistent.
- Midpoint/boundary breaks require a 1m CLOSE, not a wick.
- Snapshots are captured at T0/T+1/T+3/T+5.
- Directional price features use normalized semantics:
  positive momentum/progress always means movement in the active setup direction.
- Exact ATM option/PCR context is attached at each snapshot using the existing
  historical evidence and positioning sidecars.
- Future path labels are never features.
- No order is emitted.
- Only TRAIN + OOS-A/B/C/D are allowed. E/F/G/H remain untouched.

## Primary outcome families

RED:
- `RED_BEARISH_BREAK_AND_GO`
- `RED_BEARISH_BASE_THEN_GO`
- `RED_BREAK_BULLISH_RECLAIM`
- `RED_UNRESOLVED_30M`

GREEN:
- `GREEN_BULLISH_BREAK_AND_GO`
- `GREEN_BULLISH_BASE_THEN_GO`
- `GREEN_BREAK_BEARISH_RECLAIM`
- `GREEN_UNRESOLVED_30M`

## Reclaim outcome families

After a RED-break bullish reclaim:
- `BULLISH_RECLAIM_BREAK_AND_GO`
- `BULLISH_RECLAIM_BASE_THEN_GO`
- `FAILED_BULLISH_RECLAIM`
- `BULLISH_RECLAIM_UNRESOLVED_30M`

After a GREEN-break bearish reclaim:
- `BEARISH_RECLAIM_BREAK_AND_GO`
- `BEARISH_RECLAIM_BASE_THEN_GO`
- `FAILED_BEARISH_RECLAIM`
- `BEARISH_RECLAIM_UNRESOLVED_30M`

## What comes after this run

Do not create thresholds yet.

First inspect the 100-session counts and T+3 evidence for all four arms:

1. RED -> bearish continuation
2. RED -> bullish reclaim
3. GREEN -> bullish continuation
4. GREEN -> bearish reclaim

Then freeze TRAIN-derived decision rules separately for each arm and validate
them on OOS-A/B/C/D.
