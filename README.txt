B FAMILY — V22 100-SESSION PRE-RESEARCH HISTORICAL OOS
=========================================================

Goal
----
Scale the successful Jan-2025 V21 pilot to 100 valid trading sessions strictly
before the canonical Family-B 180-session research universe (which begins
2025-12-12).

V22 keeps BOTH of these frozen:
- canonical Family-B entry
- V20 +20 / +10m runner classifier

No exit optimization is performed.

STEP 1 — discover exactly 100 valid trading sessions
-----------------------------------------------------
cd ~/RB-ITOS-AI
source .venv/bin/activate
export PYTHONPATH=backend
set -a
source .env
set +a

python scripts/b_family_prepare_untouched_100_v22.py \
  | tee /tmp/b-family-v22-prepare.txt

STEP 2 — collect NIFTY underlying 1m
------------------------------------
python -m market_lab.historical_underlying_ohlc_sidecar \
  --underlying "NSE_INDEX|Nifty 50" \
  --manifest data/historical-validation/manifest-b-v22-untouched-100.json \
  --output data/historical-evidence/b-v22-untouched-100-underlying.json \
  --csv-output data/historical-evidence/b-v22-untouched-100-underlying.csv \
  | tee /tmp/b-family-v22-underlying.txt

Expected:
requested_session_count = 100
available_session_count = 100
row_count = 37500

STEP 3 — collect NIFTY futures 1m + causal session VWAP
--------------------------------------------------------
python -m market_lab.midpoint_v2_nifty_futures_vwap_v1 \
  --session-dates-file data/historical-validation/session-dates-b-v22-untouched-100.txt \
  --output data/historical-evidence/b-v22-untouched-100-futures-vwap.csv \
  | tee /tmp/b-family-v22-futures.txt

Expected:
100 sessions × 375 rows = 37500 rows.

STEP 4 — run frozen B + frozen V20 classifier
----------------------------------------------
python scripts/b_family_pre_research_oos_100_v22.py \
  | tee /tmp/b-family-pre-research-oos-v22.txt

Paste the full V22 validator output back.

Important
---------
Do not tune any rule during this run.
Do not modify the 10-minute window.
Do not add numerical classifier thresholds.
Do not attach a new exit model from interim results.
