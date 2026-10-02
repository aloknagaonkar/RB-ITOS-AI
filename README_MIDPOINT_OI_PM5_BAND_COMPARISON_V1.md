# ATM ±5 OI Band Comparison V1

Yes — this tests ATM ±5 directly and compares it with the existing ATM ±2 study
on the exact same 159 development events.

ATM ±5 = 11 strikes total:
ATM-5, ATM-4, ATM-3, ATM-2, ATM-1, ATM, ATM+1, ... ATM+5.

For NIFTY this module uses the existing 50-point strike spacing.

It preserves:
- overall CE/PE OI
- absolute CE/PE 5m OI change
- percentage CE/PE 5m OI change
- total absolute activity
- PCR
- identical physical strikes at current and previous checkpoint

No OOS E/F/G/H. No threshold promotion.

## Tests

```bash
cd ~/RB-ITOS-AI
source .venv/bin/activate

python -m pytest \
  tests/test_midpoint_oi_pm5_band_comparison_v1.py -v
```

## Extract ATM ±5

```bash
python -m market_lab.midpoint_oi_pm5_feature_extractor_v1 \
  --events-json data/historical-evidence/midpoint-global-session-exemplar-analysis-v1-development.json \
  --positioning 'TRAIN|data/historical-evidence/positioning-train.csv' \
  --positioning 'OOS_A|data/historical-evidence/positioning-oos-a.csv' \
  --positioning 'OOS_B|data/historical-evidence/positioning-oos-b.csv' \
  --positioning 'OOS_C|data/historical-evidence/positioning-oos-c.csv' \
  --positioning 'OOS_D|data/historical-evidence/positioning-oos-d.csv' \
  --output data/historical-evidence/midpoint-oi-pm5-features-v1-development.csv
```

## Compare ATM ±2 versus ATM ±5

```bash
python -m market_lab.midpoint_oi_band_comparison_v1 \
  --pm2 data/historical-evidence/midpoint-oi-magnitude-features-v1-development.csv \
  --pm5 data/historical-evidence/midpoint-oi-pm5-features-v1-development.csv \
  --output data/historical-evidence/midpoint-oi-band-comparison-v1-development.json
```
