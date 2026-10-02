# MIDPOINT_OI_MAGNITUDE_FEATURE_SEPARATION_V1

This is the next step after the 25-Aug forensic replay.

It tests across the existing development population whether the following
features differ between winners and losers:

- overall ATM CE OI
- overall ATM PE OI
- true 5-minute ATM CE OI change %
- true 5-minute ATM PE OI change %
- ATM ±2 total CE OI
- ATM ±2 total PE OI
- ATM ±2 CE OI change %
- ATM ±2 PE OI change %
- ATM ±2 OI PCR
- CE-vs-PE 5m OI-change divergence

No thresholds are selected.

Allowed blocks:
TRAIN, OOS_A, OOS_B, OOS_C, OOS_D

Forbidden:
OOS_E, OOS_F, OOS_G, OOS_H

## Test

```bash
cd ~/RB-ITOS-AI
source .venv/bin/activate

python -m pytest \
  tests/test_midpoint_oi_magnitude_feature_separation_v1.py -v
```

## Step 1 — Build feature CSV

Use the existing development event CSV that contains:
- block
- session_date
- direction
- confirmation_timestamp or signal_timestamp
- outcome_group = WINNER / LOSER

Example:

```bash
python -m market_lab.midpoint_oi_magnitude_feature_extractor_v1 \
  --events data/historical-evidence/<YOUR_EXISTING_EVENT_CSV>.csv \
  --positioning 'TRAIN|data/historical-evidence/positioning-train.csv' \
  --positioning 'OOS_A|data/historical-evidence/positioning-oos-a.csv' \
  --positioning 'OOS_B|data/historical-evidence/positioning-oos-b.csv' \
  --positioning 'OOS_C|data/historical-evidence/positioning-oos-c.csv' \
  --positioning 'OOS_D|data/historical-evidence/positioning-oos-d.csv' \
  --output data/historical-evidence/midpoint-oi-magnitude-features-v1-development.csv
```

## Step 2 — Compare winners vs losers

```bash
python -m market_lab.midpoint_oi_magnitude_feature_separation_v1 \
  --features data/historical-evidence/midpoint-oi-magnitude-features-v1-development.csv \
  --output data/historical-evidence/midpoint-oi-magnitude-feature-separation-v1-development.json
```

## Important

This bundle does NOT guess the event CSV path.

If your repo's global-exemplar output is JSON rather than CSV, do not manually
convert it. Run this first:

```bash
find data/historical-evidence -maxdepth 1 -type f \
  | grep -Ei 'global.*exemplar|feature.*separation|structural.*reconstruction' \
  | sort
```

Paste the matching filenames and we will wire the extractor to the exact existing
source rather than inventing a schema.

Research-only:
- threshold_tuning_performed = false
- strategy_rule_changed = false
- fresh_oos_consumed = false
- OOS E/F/G/H forbidden
