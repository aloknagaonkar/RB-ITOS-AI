# Red Bar Strategy Lab RB-0.6.5

Standalone Red Bar research application.

## Stability fixes

- Historical signal replay is idempotent. Running the same date repeatedly replaces the prior result set instead of appending duplicate rows.
- Every attempt has a deterministic `signal_id` and a unique SQLite constraint.
- Existing RB-0.3 duplicate rows are deduplicated automatically during database migration.
- Completed dates use the Upstox historical-candle endpoint and remain reusable cache artifacts.
- Today's date uses the Upstox intraday-candle endpoint and is refreshed on every download request.
- Future dates are skipped without calling Upstox.
- Today's cache is marked in the UI as `IN PROGRESS`.

## Existing strategy capabilities

- Previous 10 trading days: 15:15–15:30 15-minute midpoint
- First candle: 09:15–09:20 5-minute midpoint
- Next red candle: first bearish 5-minute candle from 09:20 onward
- Mid-session: 12:45–13:15 30-minute midpoint
- Candle A midpoint cross and immediate Candle B confirmation
- Direct transition to ACTIVE at Candle B close

## Setup

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

## Validate

```powershell
python -m pytest -q
```

## Run

```powershell
.\run_red_bar.ps1
```

Open `http://localhost:8502`.


## RB-0.4 Live monitor

The Live tab can automatically refresh the current Upstox intraday session.
Each refresh:

- updates today's one-minute cache;
- writes a current live-session snapshot under `artifacts/red_bar/data/live`;
- aggregates only completed five-minute candles;
- rebuilds currently available reference levels;
- evaluates signals idempotently;
- changes a confirmed Candle B signal to `ACTIVE`.

This release uses authenticated Upstox intraday polling. It does not yet claim
a tick-by-tick WebSocket implementation.


## RB-0.5 mixed-timeframe confirmation rule

Signal setup and confirmation now use different timeframes:

1. Candle A is a **completed 5-minute candle**.
2. Candle A must cross and **close beyond** a reference midpoint.
3. Starting immediately after Candle A closes, inspect the **next five completed
   1-minute candles**.
4. Bullish confirmation: first 1-minute candle that **closes above Candle A high**.
5. Bearish confirmation: first 1-minute candle that **closes below Candle A low**.
6. The signal becomes **ACTIVE immediately** at that 1-minute close.
7. Entry reference = confirming 1-minute close.
8. If none of the five 1-minute candles confirms, state = **TIMEOUT**.
9. If the five-minute confirmation window is still incomplete in live mode,
   state = **AWAITING_CONFIRMATION**.
10. Wick-only breaks do not confirm; the 1-minute candle must close beyond the
    setup high/low.

The existing reference levels remain unchanged.


## RB-0.6 Trade lifecycle and exit evaluation

Every ACTIVE signal can now be converted into independent paper-trade outcome
models.

Current rules:

- Entry = confirming 1-minute candle close.
- Bullish stop = setup 5-minute Candle A low.
- Bearish stop = setup 5-minute Candle A high.
- Fixed targets evaluated in parallel: 20, 30, 40 and 50 underlying points.
- Trade evaluation begins on the next completed 1-minute candle after entry.
- If stop and target are both touched in the same 1-minute candle, the
  conservative rule is applied: STOP wins.
- If neither target nor stop is hit, the trade exits at the last completed
  session candle close.
- MFE, MAE, holding minutes, exit reason and points are stored.
- Re-running the same date replaces the existing trade outcomes; it does not
  create duplicates.

This release evaluates the underlying strategy only. It does not yet simulate
historical CE/PE premium execution.


## RB-0.6.5 Bulk historical backtest

The Bulk Backtest tab processes a cached date range in one action:

1. Build/rebuild reference levels.
2. Replay signals with the RB-0.5 mixed-timeframe confirmation rule.
3. Build/refresh RB-0.6 paper trades.
4. Aggregate trade outcomes across the selected range.

The bulk runner is cache-only. It never downloads market data automatically.
Use the Historical tab first to populate any missing one-minute sessions.

The date-range summary includes trade-model count, win rate, net points,
average points and profit factor. Re-running the same range is idempotent.


See `RED_BAR_ROADMAP.md` for the updated release roadmap.
