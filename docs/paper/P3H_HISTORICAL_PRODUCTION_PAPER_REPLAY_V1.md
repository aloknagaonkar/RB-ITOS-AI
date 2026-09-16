# P3H Historical Production-Paper Replay V1

Purpose: validate the production strategy state machine on historical data without changing strategy rules.

This is **not** a tuning engine.

## Causal replay rules

- Replay one 5-minute checkpoint at a time.
- Use the first available observation in each 5-minute bucket.
- Never use a later observation from the same bucket.
- P1 uses current plus previous completed checkpoint only.
- VWAP uses only futures candles completed by that historical decision time.
- WAIT_P2 persists only to the exact next 5-minute checkpoint.
- A later checkpoint after a gap becomes `P2_CHECKPOINT_MISSED`.
- No automatic reversal.
- No paper entry in P3H V1 yet.

## Why before P3A

P3H validates production state transitions across historical sessions first.

P3A then adds:
- exact ATM CE/PE resolution
- quote freshness
- ASK-side simulated entry
- persistent paper position

## Important

Do not tune thresholds using the same replay validation sessions.

Use replay for behavior and causality validation.
Use separate research datasets for strategy changes.
