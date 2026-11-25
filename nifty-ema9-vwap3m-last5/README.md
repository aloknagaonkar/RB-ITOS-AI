# Last five sessions — unchanged EMA9 + OHLC4 VWAP / 3m

Window requested as of November4 evening: October29, October30, November2, November3, November4, 2026. NSE holiday source: https://www.nseindia.com/resources/exchange-communication-holidays?apiversion=v2 (checked November4). Weekends October31/November1 excluded. These dates are fixed; this is not an automatic rolling schedule.

## What happens on your VM

1. Resolve NIFTY front futures through official Upstox current/next-month instrument search. It must be the November2026 contract, not expired October27 or another month. November expiry is read from the provider, not hardcoded (the test fixture date is synthetic). One actual instrument key is retained across all five post-October-expiry sessions. If the November contract is no longer available in the current catalogue, block rather than substitute December; supply appropriately resolved historical contract data in a future revision.
2. Fetch 1m futures OHLCV and NIFTY50 index candles for each date using read-only GET requests. Current-date data uses intraday V3; past dates use historical V3. Require 375 exact minutes 09:15–15:29 in the SAME study window used October26. Outside-window rows are logged/excluded, never filled. This is a common research window, not a claim about any exchange session extension. Duplicates, missing minutes, wrong dates or bad volume block the complete result.
3. Run the exact same strategy source as the previous October26 package. Source SHA256 is pinned and checked. EMA9 is seeded at first completed 3m close EACH DAY; VWAP resets daily. No cross-day EMA carry is introduced, to preserve comparison assumptions. 125 completed 3m bars per session.
4. Write daily HTML/JSON/audit reports and full five-day summary, trades, peaks and giveback. Aggregate equity/drawdown is chronological across all trades, not the sum of daily drawdowns. Full result ZIP is produced only when ALL FIVE sessions are complete.

Signals: low pierces both EMA9/VWAP and close finishes above both for bullish; high pierces both and close below both for bearish. VWAP = cumulative 3m OHLC4 × futures volume / volume. Exit completed 3m close beyond EMA9. Entry/exit fills at next 3m OPEN. Equality holds for EMA exits; wick equality is not a pierce. One position; no same-signal reversal. Final open position receives the final 15:30 close mark. No 14:55 cutoff, stop/target, slope or candle-colour/body-size filter added.

Futures points primary. Index points are independent timestamp benchmarks for those same futures signals (not index-generated signals). Peak/giveback uses futures marks. No fees/slippage/options/latency. No orders, production changes or restarts.

## VM commands

Save ZIP to ~/RB-ITOS-AI and extract NEW research folder:

```bash
cd ~/RB-ITOS-AI
unzip nifty-ema9-vwap3m-last5-20261104.zip

.venv/bin/python -m pytest -q \
  nifty-ema9-vwap3m-last5/test_strategy.py \
  nifty-ema9-vwap3m-last5/test_batch.py
```

Only after tests pass, using existing VM Upstox authentication:

```bash
.venv/bin/python -u nifty-ema9-vwap3m-last5/batch.py \
  --output data/research/nifty-ema9-vwap3m-last5-20261104-v1
```

Uses UPSTOX_ACCESS_TOKEN from the process environment or existing repo .env through python-dotenv, already used by the application. It does not log credentials, request headers, or provider error bodies. Never paste tokens into chat. If access is missing/expired, use your normal VM authentication workflow. Nothing attempts interactive login or alters credentials.

Output must be new; choose another --output directory for retry. On missing/incomplete data it writes failure.json and retains whatever research inputs were fetched; it does not label a partial subset as five-day performance. Fetch count is small and requests are sequential; retries only for transient errors. No API requests, pytest or strategy replays were run in ChatGPT's environment.

Upload:

`data/research/nifty-ema9-vwap3m-last5-20261104-v1/results.zip`

Main report.html, report.json, comparison.md, daily-summary.csv, all-trades.csv, each day's full report.html/report.json/trades.csv/manifest, contract metadata and fetched inputs are included. Individual daily results.zip files are not nested into the final archive.

## References / scope

Upstox instrument search: https://upstox.com/developer/api-documentation/instrument-search/
Historical: https://upstox.com/developer/api-documentation/v3/get-historical-candle-data/
Intraday: https://upstox.com/developer/api-documentation/v3/get-intra-day-candle-data/

The collector is a read-only preparation step, never connected to order endpoints. This is after-the-fact API candle research, not original live feed recovery. First-session EMA seeding differs from charts seeded with prior days. Five sessions assess consistency but cannot establish an optimal strategy or execution profitability.
