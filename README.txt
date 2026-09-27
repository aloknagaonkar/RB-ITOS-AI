25 AUG 2026 FULL-DAY AUDIT V1.1

Fixes:
- MFE/MAE starts from the minute AFTER the entry candle.
- Entry candle high/low is excluded from post-entry excursion.
- C1 BEAR measured until first close above RED midpoint.
- C2 BEAR measured until first close above RED midpoint.
- C3 BULL measured until first close below GREEN midpoint.
- If no invalidation, measurement ends at 15:14.
- 15:15 onward remains excluded.

RUN:
cd ~/RB-ITOS-AI
source .venv/bin/activate
export PYTHONPATH=backend

python scripts/midpoint_vwap_2026_08_25_full_day_audit.py \
  | tee /tmp/midpoint-vwap-2026-08-25-full-day-audit-v1-1.txt
