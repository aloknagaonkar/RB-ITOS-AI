# MIDPOINT_GLOBAL_SESSION_EXEMPLAR_ANALYSIS_V1 FIX2

FIX2 closes the three known gaps in the first global run.

1. T3 feature VALUES
   - Reads `midpoint-failure-diagnostics-v2-2-development.json`.
   - Joins the exact T3 diagnostic row.
   - Emits actual acceptance, momentum, progress, giveback, consecutive closes, velocity.

2. Full-universe option economics
   - Adds underlying and option-OHLC inputs.
   - For every structural event, computes a COMMON retrospective economic path:
     original structural direction -> exact ATM at T3 -> next-minute OPEN.
   - This is explicitly marked counterfactual for rejected/non-traded events.
   - Actual strategy economics are preserved separately where available.
   - No nearest strike/time fallback.

3. 99 vs 100 session audit
   - Reads the previously frozen development session date list.
   - Reports exact extra/missing dates instead of guessing.

## Tests

```bash
cd ~/RB-ITOS-AI
source .venv/bin/activate

python -m pytest \
  tests/test_midpoint_global_session_exemplar_analysis_v1.py -v
```

Expected: 8 passed.

## Run

```bash
python -m market_lab.midpoint_global_session_exemplar_analysis_v1 \
  --structural data/historical-evidence/midpoint-v2-structural-reconstruction-v1-development.json \
  --stable-state data/historical-evidence/midpoint-stable-feature-state-machine-v3-2-development.json \
  --checkpoint-diagnostics data/historical-evidence/midpoint-failure-diagnostics-v2-2-development.json \
  --controlled-comparison data/historical-evidence/midpoint-oi-vwap-controlled-comparison-v1-development.json \
  --canonical-option-economics data/historical-evidence/midpoint-v3-2-exact-option-economics-v1-development.json \
  --underlying 'TRAIN|data/historical-evidence/underlying-ohlc-train.csv' \
  --underlying 'OOS_A|data/historical-evidence/underlying-ohlc-oos-a.csv' \
  --underlying 'OOS_B|data/historical-evidence/underlying-ohlc-oos-b.csv' \
  --underlying 'OOS_C|data/historical-evidence/underlying-ohlc-oos-c.csv' \
  --underlying 'OOS_D|data/historical-evidence/underlying-ohlc-oos-d.csv' \
  --positioning 'TRAIN|data/historical-evidence/positioning-train.csv' \
  --positioning 'OOS_A|data/historical-evidence/positioning-oos-a.csv' \
  --positioning 'OOS_B|data/historical-evidence/positioning-oos-b.csv' \
  --positioning 'OOS_C|data/historical-evidence/positioning-oos-c.csv' \
  --positioning 'OOS_D|data/historical-evidence/positioning-oos-d.csv' \
  --option-ohlc 'TRAIN|data/historical-evidence/option-ohlc-train.csv' \
  --option-ohlc 'OOS_A|data/historical-evidence/option-ohlc-oos-a.csv' \
  --option-ohlc 'OOS_B|data/historical-evidence/option-ohlc-oos-b.csv' \
  --option-ohlc 'OOS_C|data/historical-evidence/option-ohlc-oos-c.csv' \
  --option-ohlc 'OOS_D|data/historical-evidence/option-ohlc-oos-d.csv' \
  --futures-vwap data/historical-evidence/midpoint-v2-nifty-futures-vwap-v1-development.csv \
  --expected-session-dates-file data/historical-evidence/midpoint-v2-development-session-dates.txt \
  --sep15-intraday data/historical-evidence/intraday-validation/midpoint-oi-vwap-intraday-validation-2026-09-15.json \
  --output data/historical-evidence/midpoint-global-session-exemplar-analysis-v1-development.json
```

Inspect:

```bash
jq '{
  scope,
  coverage,
  quality_bucket_counts,
  top_bullish_by_5m,
  top_bearish_by_5m,
  bottom_bullish_by_5m,
  bottom_bearish_by_5m,
  sep7_historical_reference,
  integrity
}' \
data/historical-evidence/midpoint-global-session-exemplar-analysis-v1-development.json
```
