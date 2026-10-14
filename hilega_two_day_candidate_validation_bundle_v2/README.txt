HILEGA 30 SEP + 1 OCT ENTRY-FILTER VALIDATION
=============================================

Purpose
-------
Print every canonical Hilega signal for selected sessions with:

- entry and exit date/time/event/NIFTY price,
- direction and route,
- captured NIFTY points, MFE, MAE and giveback,
- entry RSI9, EMA3(RSI), WMA21(RSI) and EMA-WMA gap,
- causal three-bar slopes,
- flat-WMA warning,
- large-gain alignment KEEP/REJECT decision,
- flat-WMA confirmation KEEP/REJECT decision and weakness reasons,
- comparison with recorded directional audit events when available.

An early opening signal can legitimately lack a same-session three-bar slope.
Such a signal remains in the report with its control points preserved and its
candidate decision explicitly marked UNAVAILABLE. It is never silently treated
as a rejected trade. Candidate totals are compared only on available signals.

Data and causality
------------------
The unchanged canonical directional coordinator is replayed from immutable
cached one-minute NIFTY candles. Indicators are rebuilt in chronological order.
Entry decisions use only completed bars available at the signal timestamp.

Points are underlying NIFTY directional points, not option P&L.

Installed files
---------------
scripts/
  validate_hilega_entry_filters_dates.py
tests/
  test_validate_hilega_entry_filters_dates.py

Install
-------
cd ~/RB-ITOS-AI
source .venv/bin/activate
python hilega_two_day_candidate_validation_bundle/install.py

Run
---
PYTHONPATH=backend:. python \
  scripts/validate_hilega_entry_filters_dates.py \
  --dates 2026-09-30 2026-10-01

Outputs
-------
data/historical-evidence/hilega-entry-filter-date-validation-v1/
  report.json
  signal-details.csv
  daily-summary.csv

Safety
------
Read only. No live strategy, service, audit, order, paper order or quantity is
changed. No restart is required.
