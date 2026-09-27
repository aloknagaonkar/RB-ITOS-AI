B FAMILY — V23 100-SESSION PRE-V22 HISTORICAL OOS
====================================================

Goal
----
Run the previous 100 valid trading sessions immediately before V22.

V22 starts: 2025-07-17
V23 ends:   2025-07-16

Everything stays frozen:
- Family-B entry
- 10-minute delayed confirmation window
- Candidate A definition
- +20 proof
- fixed +10-minute observation
- V20 sign-only runner classifier

No exit optimization.

STEP 1 — discover exactly 100 valid sessions
--------------------------------------------
cd ~/RB-ITOS-AI
source .venv/bin/activate
export PYTHONPATH=backend
set -a
source .env
set +a

python scripts/b_family_prepare_pre_v22_100_v23.py \
  | tee /tmp/b-family-v23-prepare.txt

STEP 2 — collect NIFTY underlying 1m
------------------------------------
python -m market_lab.historical_underlying_ohlc_sidecar \
  --underlying "NSE_INDEX|Nifty 50" \
  --manifest data/historical-validation/manifest-b-v23-pre-v22-100.json \
  --output data/historical-evidence/b-v23-pre-v22-100-underlying.json \
  --csv-output data/historical-evidence/b-v23-pre-v22-100-underlying.csv \
  | tee /tmp/b-family-v23-underlying.txt

Expected:
requested_session_count = 100
available_session_count = 100
row_count = 37500

STEP 3 — collect NIFTY futures 1m + causal VWAP
------------------------------------------------
python -m market_lab.midpoint_v2_nifty_futures_vwap_v1 \
  --session-dates-file data/historical-validation/session-dates-b-v23-pre-v22-100.txt \
  --output data/historical-evidence/b-v23-pre-v22-100-futures-vwap.csv \
  | tee /tmp/b-family-v23-futures.txt

Expected:
100 sessions × 375 rows = 37500 rows.

STEP 4 — run V23 validation
---------------------------
python scripts/b_family_pre_v22_oos_100_v23.py \
  | tee /tmp/b-family-pre-v22-oos-v23.txt

Paste the full V23 validator output back.

Do not tune B or V20 rules during this run.
