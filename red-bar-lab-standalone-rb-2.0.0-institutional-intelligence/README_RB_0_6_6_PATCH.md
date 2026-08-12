# RB-0.6.6 Live Visibility Patch

This is an in-place, data-preserving patch for RB-0.6.5.

## What changes

- Shows ACTIVE signals.
- Shows AWAITING_CONFIRMATION setups.
- Shows FAILED / TIMEOUT setups.
- Shows the exact 1-minute confirmation candles checked.
- Shows the required confirmation price.
- Shows a human-readable failure/waiting reason.
- Adds a live event timeline.
- Creates a one-time SQLite backup before patched startup:
  `red_bar_strategy.pre_RB_0_6_6.db`

## What is NOT replaced

Do not replace or delete:

`artifacts/red_bar`

Your historical candles, today's live cache, database, signal history and trade
outcomes remain in place.

## Patch procedure

1. Stop Streamlit with Ctrl+C.
2. Optional manual safety copy:
   `Copy-Item .\artifacts\red_bar .\artifacts\red_bar_backup_20260807 -Recurse`
3. Copy the patch files over the existing Red Bar installation.
4. Run `python -m pytest -q`.
5. Start with `.\run_red_bar.ps1`.
6. Re-enable Auto refresh live monitor.

Today's missing 1-minute candles are backfilled from Upstox intraday data after
restart.
