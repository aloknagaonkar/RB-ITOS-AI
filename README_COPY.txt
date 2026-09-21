Branch C V2.0 — Opening-gap diagnostic

Purpose
-------
Compare the five opening-alignment sessions without imposing a new threshold.

Dates:
2026-08-10
2026-08-20
2026-08-24
2026-09-03
2026-09-18

Measures
--------
previous session close
09:15 open / close
09:20 close
09:25 close

gap points / %
gap retained % at 09:20 / 09:25
gap fill % at 09:20 / 09:25

RSI, EMA3, WMA21 at 09:15 / 09:20 / 09:25
RSI-WMA gap
EMA-WMA gap

No threshold or rejection rule is introduced.

Run tests
---------
python -m pytest tests/test_validate_hilega_milega_opening_gap_diagnostic_v2_0.py -v

Run diagnostic
--------------
python scripts/validate_hilega_milega_opening_gap_diagnostic_v2_0.py \
  --session-date 2026-08-10 \
  --session-date 2026-08-20 \
  --session-date 2026-08-24 \
  --session-date 2026-09-03 \
  --session-date 2026-09-18

CSV
---
data/historical-evidence/branch-c-opening-gap-diagnostic-v2-0.csv

Paste back:
=== BRANCH C OPENING GAP DIAGNOSTIC V2.0 ===
