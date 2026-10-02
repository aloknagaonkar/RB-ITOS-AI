# Hilega-Milega Phase 2.1 — Detailed Strategy Audit Presentation

This is a reporting/audit enhancement only. Strategy entry/exit rules are unchanged.

## Added audit detail

The canonical strategy decision audit now also records the exact 5-minute OHLC context for every evaluated candle.

Each target session now writes:

- `step-audit.jsonl` — append-only hash-chained machine audit
- `trades.csv` — completed chart-validation trades
- `signal-decision-audit.csv`
- `signal-decision-audit.json`
- `signal-decision-audit.txt` — detailed human-readable signal/candidate report
- `candle-by-candle-strategy-audit.csv`
- `candle-by-candle-strategy-audit.json`
- `candle-by-candle-strategy-audit.txt` — every completed 5m decision candle

Multi-session replay additionally writes:

- `multi-session-signal-decision-audit.csv`
- `multi-session-candle-by-candle-strategy-audit.csv`

## Human-readable signal report sections

For every meaningful signal/candidate/exit:

1. TIME / PRICE
2. INDICATORS
3. STRUCTURAL CHECKS
4. ROUTE A
5. ROUTE B
6. STRATEGY DECISION
7. INTERPRETATION
8. RETROSPECTIVE OUTCOME (entry rows only, explicitly marked as non-causal)

This makes it possible to answer exactly why a signal entered, waited, failed, exited, or was closed/cancelled by the 14:55 hard cutoff.

## Causality

Retrospective outcome is appended only after replay pairing and is clearly separated from the strategy decision evidence. It is never an input to the strategy.

## Strategy rules unchanged

This phase does not change:

- Opening path
- Path1 RSI↑EMA3 arming
- Route A
- Route B
- immediate RSI↓WMA21 structural exit
- 14:55 hard cutoff
- observation-only / execution-disabled safety

## Tests

```bash
python -m pytest \
  tests/test_hilega_milega_strategy_v1.py \
  tests/test_hilega_milega_historical_replay_v1.py \
  tests/test_live_shadow_step_audit_v1.py -v
```

Expected: `20 passed`.

## Six-session validation

```bash
set -a
source .env
set +a

python -m market_lab.hilega_milega_historical_replay_cli_v1 \
  --dates \
    2026-09-11 \
    2026-09-15 \
    2026-09-16 \
    2026-09-17 \
    2026-09-18 \
    2026-09-21
```

Review the generated `signal-decision-audit.txt` and `candle-by-candle-strategy-audit.txt` files before live-shadow integration.
