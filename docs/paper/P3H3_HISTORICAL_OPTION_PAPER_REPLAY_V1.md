# P3H.3 Historical Option Paper Replay V1

This phase extends the causal P3H.2 signal replay into a historical option-position replay.

## Entry

Only `P2_CONFIRMED_RUNTIME` can create a historical paper candidate.

- BULLISH -> exact ATM CE
- BEARISH -> exact ATM PE
- exact strike only
- no nearest-strike fallback
- maximum 4 simultaneous positions

## Historical execution model

`CHECKPOINT_CLOSE_PROXY_V1`

The historical positioning cache currently exposes CE/PE checkpoint close, not
historical bid/ask. Therefore this phase deliberately uses the exact option
checkpoint close as a **research proxy** for both entry and position marks.

This is NOT claimed to be production fill parity.

Production paper execution remains:
- entry ASK
- exit/risk monitoring BID
- quote freshness required

## Historical risk lifecycle

- hard stop: -5%
- breakeven armed: +5%
- trailing armed: +10%
- trailing distance: 3%
- no maximum holding time
- no averaging or martingale

The replay is checkpoint-close based, so it does not model intrabar stop touch
or gap-through semantics. Those require historical option OHLC/bid/ask data.

## Run

```bash
python -m market_lab.historical_option_paper_replay_cli_v1 \
  --session-date 2026-08-25 \
  --events trades
```

This output can be used to validate:
- exact ATM resolution
- position capacity
- risk-state transitions
- persistent open/closed position lifecycle
- deterministic trade accounting

Do not treat the resulting P&L as production-realistic until the historical
option OHLC/bid/ask adapter is added.
