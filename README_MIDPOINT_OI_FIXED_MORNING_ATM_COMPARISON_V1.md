# Fixed Morning ATM OI Comparison V1

This adds the second PCR/OI architecture mode requested from the beginning:
a fixed morning ATM that stays unchanged for the rest of the session.

## Fixed ATM definition

For each session:

```text
09:20 IST moving ATM
        ↓
freeze that strike
        ↓
use the same physical ATM center for every later checkpoint
```

The 09:15–09:19 opening 5-minute candle is therefore not used to define the
fixed ATM.

Both bands are calculated:

- Fixed ATM ±2 = 5 strikes
- Fixed ATM ±5 = 11 strikes

For every event, OI changes compare the same physical strikes at the causal
`oi_vwap_checkpoint_timestamp` and exactly five minutes earlier.

This is research only. No new trading threshold is promoted.

## Test

```bash
cd ~/RB-ITOS-AI
source .venv/bin/activate

python -m pytest \
  tests/test_midpoint_oi_fixed_morning_atm_comparison_v1.py -v
```

## Build fixed-ATM features

```bash
python -m market_lab.midpoint_oi_fixed_morning_atm_feature_extractor_v1 \
  --events-json data/historical-evidence/midpoint-global-session-exemplar-analysis-v1-development.json \
  --positioning 'TRAIN|data/historical-evidence/positioning-train.csv' \
  --positioning 'OOS_A|data/historical-evidence/positioning-oos-a.csv' \
  --positioning 'OOS_B|data/historical-evidence/positioning-oos-b.csv' \
  --positioning 'OOS_C|data/historical-evidence/positioning-oos-c.csv' \
  --positioning 'OOS_D|data/historical-evidence/positioning-oos-d.csv' \
  --fixed-atm-time 09:20 \
  --output data/historical-evidence/midpoint-oi-fixed-morning-atm-features-v1-development.csv
```

## Compare fixed vs moving

```bash
python -m market_lab.midpoint_oi_fixed_vs_moving_atm_comparison_v1 \
  --moving-pm2 data/historical-evidence/midpoint-oi-magnitude-features-v1-development.csv \
  --moving-pm5 data/historical-evidence/midpoint-oi-pm5-features-v1-development.csv \
  --fixed data/historical-evidence/midpoint-oi-fixed-morning-atm-features-v1-development.csv \
  --output data/historical-evidence/midpoint-oi-fixed-vs-moving-atm-comparison-v1-development.json
```

Important: if the historical positioning files do not retain the frozen morning
strikes later in the day, fixed-band coverage can be lower than 159. The output
reports this explicitly; the comparison uses only matched events.
