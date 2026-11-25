# EMA9 + OHLC4 VWAP / 3m wick rejection — standalone research

New strategy, separate from Hilega rules and its prior research. No backend/frontend files, services, broker requests or orders. Python standard library for replay/report; pytest for VM tests. Do not run strategy tests/replays locally: user runs on Ubuntu VM. Preparation here is AST source syntax and archive/input validation only.

## Agreed rules

- EMA9, not WMA9; exponential average of completed 3m closes, alpha = 2/(9+1) = 0.2.
- VWAP source is (O+H+L+C)/4 from EACH AGGREGATED 3m candle. VWAP = cumulative(source × that 3m candle's futures volume) / cumulative futures volume; reset daily at 09:15 IST. It is not the cumulative average of separately calculated 1m OHLC4 values.
- Bullish entry signal: 3m LOW < min(EMA9, VWAP) AND 3m CLOSE > max(EMA9, VWAP).
- Bearish entry signal: 3m HIGH > max(EMA9, VWAP) AND 3m CLOSE < min(EMA9, VWAP).
- A touch/equality is not a pierce. Both line values are from the completed signal candle. This is a completed-candle rejection test, not proof of an intrabar crossover of moving lines.
- Bullish exit signal: completed 3m CLOSE < EMA9. Bearish exit: CLOSE > EMA9. Equality holds.
- Entry and normal exit execute at the NEXT 3m OPEN after signal completion, including observed opening gaps. Never fill retrospectively at the signal close or at a line threshold.
- One position. No pyramiding. A bar evaluated with an active position can schedule an exit, not an additional or immediate reversal entry. A new signal can be evaluated after the exit executes and that new bar completes.
- No additional green/red body, body-percentage, EMA slope, RSI, WMA, midpoint stop, fixed stop or profit target filter is added.

## Explicit study conventions

Data: October26 2026, NIFTY FUT 27 OCT 26, expiry October27, key NSE_FO|48704. Futures volume sum 3,753,685, 375 exact regular minutes 09:15–15:29 IST, 125 completed 3m bars ending 09:18–15:30. These are supplied later API data, not original live minute recovery.

Only one futures session is available. EMA9 is seeded with the FIRST completed 3m session CLOSE, then evaluated causally without an extra nine-bar wait. This may differ from a chart using prior-session history. No futures history is invented or replaced with index prices. Before broader validation, add actual prior-session futures history for matching contract/roll conventions.

No 14:55 cutoff from the previous strategy is carried into this new study. Run the full supplied regular session. A position remaining at 15:30 receives a forced close at the final observed session CLOSE, labelled SESSION_END_MARK_CLOSE; this is a research end-of-day convention, separate from an EMA exit. No next-bar fill or new entry after the final 3m bar.

PRIMARY performance: NIFTY FUTURES price points. SECONDARY benchmark: NIFTY 50 INDEX points at identical futures entry/exit timestamps, using index opens for next-open fills and final index close for session-end marks. Signals always use FUTURES candles/EMA/VWAP; never compare futures VWAP numerically against index candles. Index benchmark is not a separately signalled index backtest. Option premium/fills/fees/slippage/latency are not modelled.

Peak profit is maximum favourable completed 1m futures CLOSE mark during the actual trade plus observed entry/exit execution marks, floored at zero. Giveback = peak − final futures points. Peak timing identifies first completed-close or exit-mark occurrence. Close-MAE excludes intraminute extremes. Closed-trade drawdown excludes intratrade excursions. Hindsight peaks are not executable targets.

## VM commands

Package includes the exact futures and index input files; no downloads, broker access or installed project code required.

Save ZIP into ~/RB-ITOS-AI, extract NEW folder:

```bash
cd ~/RB-ITOS-AI
unzip nifty-ema9-vwap3m-research-20261026.zip

.venv/bin/python -m pytest -q \
  nifty-ema9-vwap3m-research/test_strategy.py
```

Only after tests pass:

```bash
.venv/bin/python -u nifty-ema9-vwap3m-research/run.py \
  --output data/research/nifty-ema9-vwap3m-20261026-v1
```

Default inputs are bundled under the NEW research folder. Output directory must not exist; use a new directory if rerunning. Input SHA256 mismatch blocks; this first package is pinned to these exact October26 files. Supply failure.json if blocked. Do not bypass a mismatch to use another date.

Upload:

`data/research/nifty-ema9-vwap3m-20261026-v1/results.zip`

Outputs: report.html, report.json, comparison.md, trades.csv, manifest.json, results.zip. Includes every trade (entry/exit, futures and index points, peak/time/giveback, entry EMA9/VWAP) and ALL 125 completed candles with OHLC4, volume, EMA9, VWAP, qualification flags, positions, executions and entry/exit decisions.

Tests cover strict wick and close boundaries, EMA alpha, volume-weighted OHLC4, missing/negative data, next-open entry/exit fills and gaps, exit/entry priority, causal future-data invariance and position overlap. Tests/replay have NOT been executed locally; syntax validation is not a claim that VM tests passed or that strategy is profitable.
