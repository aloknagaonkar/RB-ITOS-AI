B FAMILY — 15 SEP 2026 UNSEEN VALIDATION V10.1

Fixes V10 input-schema mismatch.

Problem:
data/historical-evidence/intraday-validation/underlying-2026-09-15.csv
has timestamp/open/high/low/close/volume but no session_date column.

Fix:
V10.1 derives session_date strictly from each row's timestamp before handing
the rows to the frozen underlying_by_session() parser.

No strategy logic, Family-B logic, midpoint logic, risk parameters, runtime,
or execution settings are changed.

Run:
cd ~/RB-ITOS-AI
source .venv/bin/activate
export PYTHONPATH=backend

python scripts/b_family_unseen_2026_09_15_validation_v10_1.py \
  | tee /tmp/b-family-unseen-2026-09-15-v10-1.txt
