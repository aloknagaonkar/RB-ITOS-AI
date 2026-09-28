B FAMILY — V29 FROZEN RUNNER-EXIT CANDIDATE OOS
=====================================================

Goal
----
Freeze the first causal runner-exit candidate, then test it on the next
100 valid historical sessions strictly before V23.

V23 starts:
  2025-02-06

V29 discovery ends:
  2025-02-05

Frozen V29 candidate
--------------------
Applies only after V20 has classified a Family-B event as
RUNNER_STRENGTHENING.

Joint deterioration START:
  drawdown from running MFE using close > 0
  AND prior-minute directional futures-VWAP change < 0

At exactly +3 minutes from that episode start:
  EXIT if directional futures-VWAP is below its episode-start level
  AND directional close move has failed to recover above its episode-start level.

No magnitude threshold.
No same-episode persistence requirement.
No optimization in validation.

STEP 1 — discover 100 valid sessions
------------------------------------
cd ~/RB-ITOS-AI
source .venv/bin/activate
export PYTHONPATH=backend
set -a
source .env
set +a

python scripts/b_family_prepare_pre_v23_100_v29.py \
  | tee /tmp/b-family-v29-prepare.txt

STEP 2 — underlying 1m
----------------------
python -m market_lab.historical_underlying_ohlc_sidecar \
  --underlying "NSE_INDEX|Nifty 50" \
  --manifest data/historical-validation/manifest-b-v29-pre-v23-100.json \
  --output data/historical-evidence/b-v29-pre-v23-100-underlying.json \
  --csv-output data/historical-evidence/b-v29-pre-v23-100-underlying.csv \
  | tee /tmp/b-family-v29-underlying.txt

Expected:
  requested_session_count = 100
  available_session_count = 100
  row_count = 37500

STEP 3 — futures 1m + causal VWAP
---------------------------------
python -m market_lab.midpoint_v2_nifty_futures_vwap_v1 \
  --session-dates-file data/historical-validation/session-dates-b-v29-pre-v23-100.txt \
  --output data/historical-evidence/b-v29-pre-v23-100-futures-vwap.csv \
  | tee /tmp/b-family-v29-futures.txt

Expected:
  37500 rows

STEP 4 — frozen V29 OOS validator
---------------------------------
python scripts/b_family_runner_exit_oos_100_v29.py \
  | tee /tmp/b-family-runner-exit-oos-v29.txt

Paste the complete V29 output back.

Do not tune V29 based on intermediate results.
