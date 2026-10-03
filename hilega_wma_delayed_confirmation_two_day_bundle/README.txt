HILEGA POST-SIGNAL WMA DELAYED CONFIRMATION — TWO-DAY VALIDATION
================================================================

This is research-only. The unchanged canonical Hilega strategy produces every
signal first. The validator then checks the forming five-minute indicator after
each completed one-minute candle for up to ten minutes.

Rule
----
Bullish raw WMA change >= +0.75: confirmed.
Bearish raw WMA change <= -0.75: confirmed.
Directional magnitude >= 1.00: strong.
The original canonical Hilega signal must remain active. Full directional
RSI/EMA/WMA alignment is reported as a diagnostic, not as another entry gate.
No confirmation by T+10: no entry.

The reference is the latest completed five-minute WMA21 of RSI9. During each
forming five-minute slot the reference remains fixed; it rolls forward only
when another five-minute candle becomes completed.

Folder structure
----------------
~/RB-ITOS-AI/
├── hilega_wma_delayed_confirmation_two_day_bundle/
│   ├── install.py
│   └── files/
│       ├── scripts/
│       │   └── validate_hilega_wma_delayed_confirmation.py
│       └── tests/
│           └── test_validate_hilega_wma_delayed_confirmation.py
├── scripts/
└── tests/

Install
-------
cd ~/RB-ITOS-AI
source .venv/bin/activate
python hilega_wma_delayed_confirmation_two_day_bundle/install.py

Run
---
PYTHONPATH=backend:. python \
  scripts/validate_hilega_wma_delayed_confirmation.py \
  --dates 2026-09-30 2026-10-01

Outputs
-------
data/historical-evidence/
  hilega-wma-delayed-confirmation-2026-09-30-2026-10-01-v1/
    report.json
    trade-validation.csv
    minute-by-minute-wma.csv

trade-validation.csv reports the original signal, first 0.75 confirmation,
first 1.00 confirmation, first fully aligned delayed entry, canonical points,
and delayed-entry points.

minute-by-minute-wma.csv contains every one-minute observation used, including
the completed five-minute reference, provisional RSI/EMA/WMA values, raw and
direction-normalized WMA change, alignment, close and points from original
entry.

No restart is required.
