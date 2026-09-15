# MIDPOINT_OI_MAGNITUDE_FEATURE_SEPARATION_V1_FIX1

The global exemplar source is JSON and contains a top-level `events` array.

Each event includes fields such as:
- block
- session_date
- direction
- decision_family
- signal_timestamp
- net_5m_pct

This FIX1 reads that JSON directly.

Outcome grouping:
- WINNER: net_5m_pct >= 3
- SMALL_WIN: 0 < net_5m_pct < 3  (excluded)
- LOSER: net_5m_pct <= 0

This mirrors the earlier descriptive winner/loser separation:
GOOD + EXCELLENT vs LOSS + LARGE_LOSS, with SMALL_WIN excluded.

Allowed blocks:
TRAIN, OOS_A, OOS_B, OOS_C, OOS_D

Forbidden:
OOS_E, OOS_F, OOS_G, OOS_H

## Test

```bash
cd ~/RB-ITOS-AI
source .venv/bin/activate

python -m pytest \
  tests/test_midpoint_oi_magnitude_feature_extractor_v1_fix1.py \
  tests/test_midpoint_oi_magnitude_feature_separation_v1.py -v
```

## Extract

```bash
python -m market_lab.midpoint_oi_magnitude_feature_extractor_v1_fix1 \
  --events-json data/historical-evidence/midpoint-global-session-exemplar-analysis-v1-development.json \
  --positioning 'TRAIN|data/historical-evidence/positioning-train.csv' \
  --positioning 'OOS_A|data/historical-evidence/positioning-oos-a.csv' \
  --positioning 'OOS_B|data/historical-evidence/positioning-oos-b.csv' \
  --positioning 'OOS_C|data/historical-evidence/positioning-oos-c.csv' \
  --positioning 'OOS_D|data/historical-evidence/positioning-oos-d.csv' \
  --output data/historical-evidence/midpoint-oi-magnitude-features-v1-development.csv
```

If any positioning filename does not exist, list them with:

```bash
find data/historical-evidence -maxdepth 1 -type f \
  | grep -Ei 'positioning.*(train|oos)' \
  | sort
```

## Separate

```bash
python -m market_lab.midpoint_oi_magnitude_feature_separation_v1 \
  --features data/historical-evidence/midpoint-oi-magnitude-features-v1-development.csv \
  --output data/historical-evidence/midpoint-oi-magnitude-feature-separation-v1-development.json
```

No thresholds are selected in this experiment.
