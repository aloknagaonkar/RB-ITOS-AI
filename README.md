# Hilega NIFTY O→C / Δ + clean timing patch

Frontend-only.

Changes the live/historical decision table to:
- show candle window in the first column
- show the actual processing time below it without the word `processed`
- retain `recovered HH:MM:SS` only for bootstrap-recovered provenance
- change the NIFTY column to `NIFTY O → C / Δ from entry`
- show candle Open → Close on line 1 and trade delta on line 2

No backend, strategy, worker, option lifecycle, or evidence changes.
