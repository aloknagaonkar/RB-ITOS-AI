# Hilega-Milega Bullish Strategy Engine V1 — Phase 1

This phase introduces the canonical, observation-only Hilega-Milega bullish strategy engine.
It does **not** wire the strategy into live shadow or historical multi-session replay yet.

## Canonical rules

- Indicators: RSI(9), EMA(3) of RSI, WMA(21) of RSI.
- Opening path:
  - 09:15 full alignment: RSI > 50, EMA3 > 50, WMA21 > 50, RSI > EMA3 > WMA21.
  - 09:20 RSI > WMA21.
  - 09:25 RSI > WMA21 -> bullish entry.
- Path1 arm: RSI crosses EMA3 upward.
- Route A: same cross candle, RSI > 50 and RSI > WMA21.
- Route B: while armed, `(RSI > WMA21 OR EMA3 > WMA21)` and RSI rising and EMA3 rising.
- Structural exit: first RSI cross below WMA21.
- Hard session cutoff: at 14:55 close active shadow position at the 14:55 candle OPEN, cancel armed/opening state, and block all new entries for the session.

## Explicitly excluded research rules

The engine does not contain WMA3 filters, RSI/WMA or EMA/WMA gap thresholds, 3-candle confirmation, +20 profit handling, trailing stops, option quantity, or broker execution.

## Causality and indicator history

Indicator history continues across sessions for warmup parity with the validated research scripts. Strategy state resets on a new session.

## Audit

When supplied a `ShadowStepAuditStoreV1`, the engine records decision and transition steps into the existing append-only hash-chained audit store.

## Safety

- `OBSERVATION_ONLY = True`
- `EXECUTION_ENABLED = False`
- `PAPER_ORDER_ENABLED = False`

## Phase-1 test

```bash
source .venv/bin/activate
python -m pytest tests/test_hilega_milega_strategy_v1.py tests/test_live_shadow_step_audit_v1.py -v
```

Phase 2 will connect this exact engine to historical replay and perform parity validation before any live-shadow wiring.
