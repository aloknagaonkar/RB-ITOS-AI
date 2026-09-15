# OI Pattern Library 90D V1

Builds a reusable OI pattern library from the latest 90 historical sessions
and compares every available current-day 5-minute checkpoint against it.

Current day is **external only**: it is never used to fit historical scaling.

Primary feature set:
- moving ATM ±2 CE/PE absolute OI deltas
- CE/PE 5m percentage changes
- total absolute activity
- PCR + PCR change
- ATM CE/PE premium change when present
- LB/SB/SC/LU states when premium fields are present
- fixed 09:20 ATM ±2 context
- historical +5/+10/+15 minute spot outcomes

No trading rule is selected.

## Test

```bash
cd ~/RB-ITOS-AI
source .venv/bin/activate
python -m pytest tests/test_oi_pattern_library_90d_v1.py -v
```

## Build 90-session library and include Sep 15 as external current day

```bash
python -m market_lab.oi_pattern_library_90d_v1 \
  --historical-positioning 'TRAIN|data/historical-evidence/positioning-train.csv' \
  --historical-positioning 'OOS_A|data/historical-evidence/positioning-oos-a.csv' \
  --historical-positioning 'OOS_B|data/historical-evidence/positioning-oos-b.csv' \
  --historical-positioning 'OOS_C|data/historical-evidence/positioning-oos-c.csv' \
  --historical-positioning 'OOS_D|data/historical-evidence/positioning-oos-d.csv' \
  --current-positioning data/historical-evidence/intraday-validation/positioning-5min-2026-09-15.csv \
  --latest-sessions 90 \
  --fixed-atm-time 09:20 \
  --top-n 10 \
  --output data/historical-evidence/intraday-validation/oi-pattern-library-90d-v1-2026-09-15.json
```

## Print compact current-day comparison

```bash
python -m market_lab.oi_pattern_library_90d_report_v1 \
  --input data/historical-evidence/intraday-validation/oi-pattern-library-90d-v1-2026-09-15.json \
  --last 12
```

Notes:
- only exact timestamps whose minute is divisible by 5 are used;
- each feature compares T to exact T-5m using the same physical strikes;
- latest 90 unique session dates are selected from TRAIN/OOS_A-D;
- OOS_E/F/G/H are rejected if passed as historical inputs;
- current-day forward outcomes are not needed and not used.
