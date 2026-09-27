25 AUG 2026 FULL-DAY AUDIT V1
================================

This is intentionally a single-session research audit.

Trusted window:
  09:15–15:14

Explicitly excluded:
  15:15 onward

The script validates the three current trade candidates:
  09:42 BEARISH — delayed full Candidate A
  12:00 BEARISH — failed RED-midpoint reclaim + RED-low rebreak
  14:31 BULLISH — structural recovery + GREEN-high / RED-high rebreak

It measures:
  +1/+3/+5/+10/+15 minute directional movement
  MFE through 15:14
  MAE through 15:14
  structural invalidation timestamps
  full minute-level structural/VWAP audit

INSTALL
-------
Copy:
  scripts/midpoint_vwap_2026_08_25_full_day_audit.py

to:
  ~/RB-ITOS-AI/scripts/

RUN
---
cd ~/RB-ITOS-AI
source .venv/bin/activate
export PYTHONPATH=backend

python scripts/midpoint_vwap_2026_08_25_full_day_audit.py \
  | tee /tmp/midpoint-vwap-2026-08-25-full-day-audit.txt

Do not interpret this as a production strategy.
No Hilega changes.
No Candidate A changes.
No runtime changes.
No execution/orders/quantity.
