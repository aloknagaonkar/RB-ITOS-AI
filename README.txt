B FAMILY FIVE-DAY VALIDATION V1

Days:
2026-06-17
2026-06-22
2026-06-30
2026-07-13
2026-07-14

Run:
cd ~/RB-ITOS-AI
source .venv/bin/activate
export PYTHONPATH=backend

python scripts/b_family_five_day_validation_v1.py \
  | tee /tmp/b-family-five-day-validation-v1.txt

Report includes:
- total B cases per day
- entry time and price
- FUT-VWAP
- +1/+3/+5/+10/+15m underlying NIFTY points
- MFE / MAE
- invalidation
- entry-to-invalidation points when exact invalidation close is available

Research only. No runtime/execution changes.
