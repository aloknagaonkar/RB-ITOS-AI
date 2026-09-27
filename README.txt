B FAMILY FIVE-DAY VALIDATION V2

Adds to V1:
- exact B entry time
- timestamp where maximum favorable NIFTY excursion was achieved
- best favorable NIFTY level
- structural invalidation time
- points from entry to invalidation

Run:
cd ~/RB-ITOS-AI
source .venv/bin/activate
export PYTHONPATH=backend

python scripts/b_family_five_day_validation_v2.py \
  | tee /tmp/b-family-five-day-validation-v2.txt

Important:
"Best exit time" is the hindsight MFE timestamp. It is NOT a frozen live exit rule.
