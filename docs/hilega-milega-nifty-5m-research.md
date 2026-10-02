# Hilega-Milega: NIFTY 5-minute comparison

The RSI-50-filtered EMA/WMA crossover was the least loss-making of the three
tested rules after a hypothetical 2-point round-trip cost. None demonstrated
positive net performance on both the training and held-out periods. This does
not establish a profitable strategy or a universal best rule.

## Data and fixed experiment

- Source: Upstox historical candle API v3, Nifty 50 index, 5-minute OHLC.
- Requested dates: 2025-09-01 through 2026-09-17.
- 259 complete regular sessions, 19,425 candles; first five sessions warm up indicators.
- One nonregular session, 2025-10-21 (12 candles), excluded.
- Training: 177 sessions, 2025-09-08 through 2026-05-29.
- Holdout: 77 sessions, 2026-06-01 through 2026-09-17.
- RSI(9) on close; EMA(3) and WMA(21) of that RSI, unchanged across rules.
- Both long and short; signal at candle close, fill at next candle open.
- Exit on opposite raw crossover; reverse only if the new entry qualifies.
- Filtered entry requires RSI > 50 for long and < 50 for short at the crossover.
- Fresh cross required: a later RSI confirmation alone does not open a trade.
- Exit all positions at 15:20 IST open; no overnight exposure.
- No protective stop or profit target in this entry-rule baseline.
- Candidate selected by training net points at 2 points round-trip cost,
  before interpreting holdout performance. No parameter sweep was performed.

## Results

All returns below subtract 2 hypothetical index points per completed trade.

| Rule | Train net points | Holdout trades | Holdout net points | Holdout profit factor | Holdout closed-trade drawdown |
| --- | ---: | ---: | ---: | ---: | ---: |
| EMA(3)/WMA(21) crossover | -3,657.90 | 670 | -1,245.60 | 0.857 | 1,426.10 |
| Same crossover, RSI-50 entry filter | -980.80 | 417 | -438.95 | 0.909 | 1,044.00 |
| RSI crosses 50 | -2,057.65 | 803 | -1,832.70 | 0.789 | 2,195.30 |

The filtered rule earned 395.05 gross holdout points across 417 trades:
only about 0.95 points per trade before costs. At 5 points round-trip cost it
lost 1,689.95 points. Its holdout long trades lost 607.25 points and short trades
earned 168.30 points at 2 points cost. Selecting short-only based on this result
would be a new hypothesis needing a new untouched evaluation period.

## Practical limits

These are directional index-point simulations, not actual futures or option P&L.
The cost scenarios (0, 2, 5, 10 points) are sensitivity assumptions, not verified
broker fees. Futures basis, contract rolls, lot sizes, margin and option dynamics
are not modeled. Drawdown is measured at closed trades, so intratrade risk can
be larger. Whole missing sessions are not detected without an exchange calendar.
Indicators carry between retained complete sessions. The held-out dates were not
used by this script for selection, but may overlap previous project research.
Python calculations and fills have unit tests; TradingView parity has not been
verified by comparing exported indicator values and trades.

The next useful experiment is a separately specified trend or trade-management
rule with actual execution-instrument costs and fresh validation data. The
current evidence does not support trading these baseline rules as-is.

## Reproduce

```powershell
.venv\Scripts\python.exe -m market_lab.hilega_milega_research --fetch
.venv\Scripts\python.exe -m pytest tests/test_hilega_milega_research.py -q
```

Omit `--fetch` to use the locally cached candles. Outputs are in
`data/hilega-milega-research/`: raw candle responses, `report.json` with cost,
month and side breakdowns, and `trades.csv` with every simulated trade.

References:
- https://upstox.com/developer/api-documentation/v3/get-historical-candle-data/
- https://www.tradingview.com/pine-script-docs/concepts/strategies/
