B FAMILY — V45 THIRD HISTORICAL VALIDATION

Range:
2024-08-16 through 2025-02-05

Frozen candidate:
PRIMARY_OFF + CAP20

No tuning grid.

Run:

cd ~/RB-ITOS-AI
source .venv/bin/activate
export PYTHONPATH=backend

python scripts/b_family_primary_off_cap20_validation_v45.py \
  | tee /tmp/b-family-primary-off-cap20-validation-v45.txt

Paste the complete output back.
