# Normal Route — November validation

Research only. Strategy version normal-route-rsi5-ema30-0.3.0. Entry/exit rules unchanged from the runner used for 20/23 November. This bundle adds month selection, short-session support and a filterable monthly HTML report. No production source, services, journals, broker connections, or original candle caches are modified.

Run from RB-ITOS-AI on the VM (requires installed bounded-warmup module and existing verified November/October caches):

```bash
.venv/bin/python -u -B normal-route-november-v1/run.py --month 2026-11 --through 2026-11-23
```

Days after 23 November are outside this report. Calendar weekends and holidays are listed as NON_TRADING_DAY. Missing or invalid target/warmup data is REPLAY_FAILED, not a successful zero-trade day; the final ZIP is still written and the command exits 2. No network fetch is attempted. Each replay reads raw minute candles and recomputes indicators from exactly 20 verified prior sessions; existing replay results are not reused.

## Rules

Completed 3-minute candles. CE: close > EMA30(high), green close > open, RSI5/9/14/21/28 each >55, WMA21(RSI9)>50. PE: close < EMA30(low), red close < open, all five RSIs <45, WMA21(RSI9)<50. All eight gates required. Strict inequalities; doji fails.

CE exit requires all three groups on the same completed candle: (RSI5<50 AND RSI9<50) AND WMA21(RSI9)<50 AND close<EMA30(low). PE: (RSI5>50 AND RSI9>50) AND WMA21(RSI9)>50 AND close>EMA30(high). Independent mandatory 15:30 close; no new entry then. Single owner; exit processed before a fully qualified opposite entry. RSI14/21/28 are entry gates only.

Signals at 3m completion; ordinary simulated fills use next 1m open. Session end uses exact 15:29 close. MFE uses held minute highs/lows; giveback = MFE − realized directional points. NIFTY points only, no option premium, fees or slippage. Summed trade peaks are not a realizable return.

8 November is explicitly supported using its verified 70 minutes (14:20–15:29). The incomplete leading 14:20 bucket is excluded, yielding 23 complete 3m bars from 14:21, first decision/fill 14:24, final close 15:30. No padding. Other dates retain the strict 125-bar 09:15 grid.

## Output

Printed HTML and UPLOAD ZIP paths under data/research/normal-route-november-<timestamp>.

- audit.html: date selector, bullish/CE or bearish/PE selector, separate descriptive day-trend filter. Filters update trades, daily totals and aggregate points. Both directions' detailed rule checks, blockers, position owner, accepted events and active-position exit checks on every completed candle. Entry and exit indicator snapshots per trade.
- results.json: raw research evidence, all candle audits, input hashes, coverage, per-day and aggregate results.
- daily-summary.csv, trades.csv, candle-audit.csv for analysis (empty trade CSV omitted if no trades).

Day trend is close versus session open, calculated after the session. It is descriptive and is never a strategy entry filter. Selecting a trade direction shows that side's entry audit even while the opposite position owns the strategy; active exit evidence remains visible for context.

Tests: `python3 -m unittest discover -s normal-route-november-v1/tests -v`. Browser filter logic test requires Node; engine tests use Python standard library. Tests use synthetic candles and canonical indicator fixture, not November performance evidence. To independently validate month performance, run on VM and return the printed result ZIP.
