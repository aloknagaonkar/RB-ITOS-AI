# OI Pattern Library 90D Historical-Only V1

This is the clean historical-only version.

It uses only TRAIN + OOS_A-D positioning CSVs and selects the latest 90 unique
sessions from that pool.

Primary OI strength:
- Moving ATM ±2
- five strikes only
- same physical strikes at T and exact T-5m
- strength = abs(CE delta) + abs(PE delta)

Secondary context:
- Fixed 09:20 ATM ±2

It also retains:
- CE/PE current OI
- signed CE/PE OI delta
- CE/PE 5m OI percentage
- PCR and PCR change
- ATM CE/PE premium change
- CE/PE LB/SB/SC/LU state
- +5/+10/+15 minute spot outcomes

No database.
No Sep-15/current day.
No OOS E/F/G/H.
No strategy or execution change.

## Test

```bash
cd ~/RB-ITOS-AI
source .venv/bin/activate

python -m pytest \
  tests/test_oi_pattern_library_90d_historical_only_v1.py -v
```

## Build latest 90 historical sessions

```bash
python -m market_lab.oi_pattern_library_90d_historical_only_v1 \
  --positioning 'TRAIN|data/historical-evidence/positioning-train.csv' \
  --positioning 'OOS_A|data/historical-evidence/positioning-oos-a.csv' \
  --positioning 'OOS_B|data/historical-evidence/positioning-oos-b.csv' \
  --positioning 'OOS_C|data/historical-evidence/positioning-oos-c.csv' \
  --positioning 'OOS_D|data/historical-evidence/positioning-oos-d.csv' \
  --latest-sessions 90 \
  --fixed-atm-time 09:20 \
  --output data/historical-evidence/oi-pattern-library-90d-historical-only-v1.json \
  --csv-output data/historical-evidence/oi-pattern-library-90d-historical-only-v1.csv
```

## Print summary

```bash
python -m market_lab.oi_pattern_library_90d_historical_only_report_v1 \
  --input data/historical-evidence/oi-pattern-library-90d-historical-only-v1.json
```

Interpretation warning:
The pattern families are descriptive research labels, not trading rules.
