# Current exit warning, then five-minute price EMA10

Run from RB-ITOS-AI root:

```bash
python hilega_ema10_warning_exit_research/research.py --self-test &&
python hilega_ema10_warning_exit_research/research.py
```

Inputs are the existing reconciled 490-session adjacent-gap report and Nifty minute cache. Python standard library only. No installer, restart, API or broker calls. An existing output directory is never overwritten; use --output-root for reruns.

Exit sequence:
1. Keep each tested entry unchanged.
2. Existing canonical structural exit becomes a latched warning.
3. On that completed candle or later, bullish exits when Nifty close < five-minute price EMA10; bearish exits when close > EMA10. Equality waits. EMA10 conditions before the warning are ignored. The warning does not reset if RSI recovers.
4. Mandatory 14:55 candle-open exit has priority and remains unchanged.

EMA10 uses completed five-minute Nifty closes, starts with the first ten-close SMA and carries across cached trading sessions. Candle labels are open timestamps; a 10:00 candle's close/EMA is available at 10:05. The script verifies that the current warning price matches the source candle close (or cutoff open), and that current P&L reconciles. It stops on inconsistency.

Entry comparisons: current waiting entry, unfiltered earlier adjacent-gap entry, and bullish expansion 0.25–0.50 hybrid with bearish waiting retained. No entry thresholds are fitted here.

Output: data/historical-evidence/hilega-warning-ema10-exit-v1/
- report.json: all data and per-candle post-warning close/EMA10 evaluations.
- summary.csv: paired exits, bullish/bearish and development blocks, gains/losses, ratios, completed-trade drawdown, winner-to-loser changes, giveback and overlap counts.
- trade-exits.csv: entry, warning and exit timestamps/prices, extra holding time, points, MFE/MAE, giveback and overlap flags.
- gap_bands.csv: entry-gap size and expansion grouped with both exit outcomes.

Gap bands use actual earlier-entry data only. Waiting-entry gap values are marked UNAVAILABLE rather than borrowing values from a different entry time. Both winners and losers remain in every band; gap bands are descriptive, not a guarantee or validated best threshold.

IMPORTANT: This is a paired exit attribution study, not a sequential portfolio backtest. Extended holding may overlap original later entries; the script reports this explicitly. Successful paired results require a new sequential replay with position ownership before promotion. Existing entries and canonical warning times are held fixed to isolate exit changes. Current or future live behavior is not altered.

MFE/MAE use minute ranges from entry until the exit decision time, excluding that decision minute and the cutoff candle's future range. Giveback equals MFE minus final points; losses may therefore produce giveback larger than MFE. Fee/slippage, option P&L and broker fill modelling are excluded. Frozen warmup reconciliation remains research evidence, not a live indicator repair.

Local validation: rule self-tests and 23 signals from recovered October 6/7 data. Full 490-session results must be generated on the VM. No best exit is selected from the small sample.

Timing correction: entries later than the warning decision or at/after 14:55 are not usable paired trades. They are recorded in excluded-entries.csv with trade, policy, timestamps, reason and original source points. Both methods exclude the same pairs. Each summary reports excluded_timing_entries and excluded_source_points. These are eligible-subset results; do not compare them directly to the complete original strategy totals. Equality at a structural warning remains eligible under the existing source timestamp convention. No timestamps are shifted and no missed entry is invented. Investigate excluded source rows separately before sequential replay. Other parity errors still stop research.
