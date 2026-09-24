# Hilega Bearish Phase B1/B2

Adds a separate candidate bearish Hilega engine without changing the working bullish engine.

Implemented candidate mirror rules:
- Opening: 09:15 RSI<50, EMA<50, WMA<50, RSI<EMA<WMA; 09:20 RSI<WMA; 09:25 RSI<WMA
- Arm: fresh RSI cross below EMA3
- Route A: fresh cross + RSI<50 + RSI<WMA21
- Route B: armed + (RSI<WMA21 or EMA3<WMA21) + RSI falling + EMA falling
- Exit: fresh RSI cross above WMA21
- Cutoff: 14:55 OPEN, lock session, no new entries

This phase is intentionally isolated:
- no directional coordinator yet
- no PE option lifecycle yet
- no live worker wiring yet
- no modification to bullish production behavior

Validated against the uploaded source snapshot:
`22 passed` across the existing bullish strategy tests and the new bearish strategy tests.
