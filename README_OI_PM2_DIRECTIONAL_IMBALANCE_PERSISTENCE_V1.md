# OI PM2 Directional Imbalance Persistence V1

Uses the frozen trend-day files only:

- `bullish-trend-days-90d-v1.txt`
- `bearish-trend-days-90d-v1.txt`

No reclassification is performed.

Core feature:

`directional_imbalance = PE signed OI delta - CE signed OI delta`

Positive is treated as bullish-side quantity imbalance for descriptive research.
Negative is treated as bearish-side quantity imbalance.

The study measures same-sign persistence over:
- 1 checkpoint = 5m
- 2 checkpoints = 10m
- 3 checkpoints = 15m
- 4 checkpoints = 20m

PCR sign agreement is measured separately. No threshold is selected.

## Test

```bash
cd ~/RB-ITOS-AI
source .venv/bin/activate

python -m pytest \
  tests/test_oi_pm2_directional_imbalance_persistence_v1.py -v
```

## Run

```bash
python -m market_lab.oi_pm2_directional_imbalance_persistence_v1 \
  --bullish-dates data/historical-evidence/bullish-trend-days-90d-v1.txt \
  --bearish-dates data/historical-evidence/bearish-trend-days-90d-v1.txt \
  --positioning 'TRAIN|data/historical-evidence/positioning-train.csv' \
  --positioning 'OOS_A|data/historical-evidence/positioning-oos-a.csv' \
  --positioning 'OOS_B|data/historical-evidence/positioning-oos-b.csv' \
  --positioning 'OOS_C|data/historical-evidence/positioning-oos-c.csv' \
  --positioning 'OOS_D|data/historical-evidence/positioning-oos-d.csv' \
  --output data/historical-evidence/oi-pm2-directional-imbalance-persistence-v1.json \
  --csv-output data/historical-evidence/oi-pm2-directional-imbalance-persistence-v1.csv
```

## Report

```bash
python -m market_lab.oi_pm2_directional_imbalance_persistence_report_v1 \
  --input data/historical-evidence/oi-pm2-directional-imbalance-persistence-v1.json
```

Interpretation remains research-only. Do not convert any percentage shown by this study directly into a trading threshold.
