# MIDPOINT_GLOBAL_SESSION_EXEMPLAR_ANALYSIS_V1

Whole-history descriptive study across all development sessions and structural events.

Goals:
- analyze all historical TRAIN + OOS_A/B/C/D sessions
- include all leakage-safe structural events, not only Arm C survivors
- analyze both bullish and bearish families
- identify best/worst option outcomes
- compare Sep-07 historical setup(s)
- optionally attach Sep-15 current-day intraday case as external reference
- no tuning, no promotion

## Run

```bash
cd ~/RB-ITOS-AI
source .venv/bin/activate

python -m pytest \
  tests/test_midpoint_global_session_exemplar_analysis_v1.py -v

python -m market_lab.midpoint_global_session_exemplar_analysis_v1 \
  --structural data/historical-evidence/midpoint-v2-structural-reconstruction-v1-development.json \
  --stable-state data/historical-evidence/midpoint-stable-feature-state-machine-v3-2-development.json \
  --controlled-comparison data/historical-evidence/midpoint-oi-vwap-controlled-comparison-v1-development.json \
  --canonical-option-economics data/historical-evidence/midpoint-v3-2-exact-option-economics-v1-development.json \
  --positioning 'TRAIN|data/historical-evidence/positioning-train.csv' \
  --positioning 'OOS_A|data/historical-evidence/positioning-oos-a.csv' \
  --positioning 'OOS_B|data/historical-evidence/positioning-oos-b.csv' \
  --positioning 'OOS_C|data/historical-evidence/positioning-oos-c.csv' \
  --positioning 'OOS_D|data/historical-evidence/positioning-oos-d.csv' \
  --futures-vwap data/historical-evidence/midpoint-v2-nifty-futures-vwap-v1-development.csv \
  --sep15-intraday data/historical-evidence/intraday-validation/midpoint-oi-vwap-intraday-validation-2026-09-15.json \
  --output data/historical-evidence/midpoint-global-session-exemplar-analysis-v1-development.json
```

Inspect:

```bash
jq '{
  scope,
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

Important:
- expected historical scope is about 99 unique sessions and 184 structural events
- Sep-15 is external/current-day reference only
- realized outcome rankings are retrospective research only
