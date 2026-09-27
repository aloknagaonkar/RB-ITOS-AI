B FAMILY — 15 SEP 2026 UNSEEN VALIDATION V10
==============================================

This is the first actual post-08-Sep untouched-session validation.

Why 15 Sep?
-----------
The repo already contains both:
- data/historical-evidence/intraday-validation/underlying-2026-09-15.csv
- data/historical-evidence/intraday-validation/futures-vwap-2026-09-15.csv

The frozen midpoint framework's structural event generation is based on
underlying OHLC. Evidence/positioning are attached to snapshot context only,
so this adapter suppresses that context rather than fabricating it.

The script imports directly:
- frozen opening_candle_midpoint_framework_v1 structural functions
- frozen family_b_for_event() / measure_event()
- unchanged V8.2 risk functions

Run:
----
cd ~/RB-ITOS-AI
source .venv/bin/activate
export PYTHONPATH=backend

python scripts/b_family_unseen_2026_09_15_validation_v10.py \
  | tee /tmp/b-family-unseen-2026-09-15-v10.txt

Paste the complete output back.

Research only. No runtime or execution changes.
