# P3H.5.2 — Single-Session Data Gate V1

For each canonical date: validate positioning/OI, option 1m OHLC, futures 1m OHLCV+VWAP, and a genuine 09:20 OI baseline. Strategy replay is blocked unless the gate passes.

```bash
python -m market_lab.session_data_gate_v1 --session-date 2026-05-04
```

Only after PASS:

```bash
python -m market_lab.session_strategy_replay_v1 --session-date 2026-05-04 --events exits
```

If FAIL, repair only the failed source and rerun the gate. No nearest-date substitution or synthetic replacement.
