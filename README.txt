V29.1 DATA-INTEGRITY REPAIR
============================

Why
---
V29 preparation accepted 2024-11-29 because NIFTY underlying had 375 bars.
The canonical futures collector returned no 1-minute candles for that session,
so the V29 validator correctly stopped.

Do NOT tune V29 and do NOT bypass the missing futures session.

V29.1 rebuilds the 100-session universe requiring BOTH:
- underlying = exactly 375 rows
- futures = exactly 375 rows using the canonical futures collector

The V29 exit hypothesis itself is unchanged.

1. Run dual-validity repair
---------------------------
cd ~/RB-ITOS-AI
source .venv/bin/activate
export PYTHONPATH=backend
set -a
source .env
set +a

python scripts/b_family_repair_dual_valid_100_v29_1.py \
  | tee /tmp/b-family-v29_1-dual-valid.txt

2. Regenerate underlying using repaired manifest
------------------------------------------------
python -m market_lab.historical_underlying_ohlc_sidecar \
  --underlying "NSE_INDEX|Nifty 50" \
  --manifest data/historical-validation/manifest-b-v29-pre-v23-100.json \
  --output data/historical-evidence/b-v29-pre-v23-100-underlying.json \
  --csv-output data/historical-evidence/b-v29-pre-v23-100-underlying.csv \
  | tee /tmp/b-family-v29-underlying-repaired.txt

Expected: 100 / 100, 37500 rows.

3. Regenerate futures
---------------------
rm -f data/historical-evidence/b-v29-pre-v23-100-futures-vwap.csv

python -m market_lab.midpoint_v2_nifty_futures_vwap_v1 \
  --session-dates-file data/historical-validation/session-dates-b-v29-pre-v23-100.txt \
  --output data/historical-evidence/b-v29-pre-v23-100-futures-vwap.csv \
  | tee /tmp/b-family-v29-futures-repaired.txt

Expected: 37500 rows.

4. Only then run the frozen V29 validator
-----------------------------------------
python scripts/b_family_runner_exit_oos_100_v29.py \
  | tee /tmp/b-family-runner-exit-oos-v29.txt
