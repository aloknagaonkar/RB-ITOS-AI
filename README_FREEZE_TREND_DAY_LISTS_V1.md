# Freeze Trend Day Lists V1

This utility freezes the bullish/bearish date selection from the already-created:

`DAY_TREND_CLASSIFICATION_90D_V1`

It does **not** recalculate direction and does **not** use OI/PCR.

Outputs:
- `data/historical-evidence/bullish-trend-days-90d-v1.txt`
- `data/historical-evidence/bearish-trend-days-90d-v1.txt`
- `data/historical-evidence/trend-day-lists-90d-v1-manifest.json`

## Test

```bash
cd ~/RB-ITOS-AI
source .venv/bin/activate

python -m pytest tests/test_freeze_trend_day_lists_v1.py -v
```

## Freeze the lists

```bash
python -m market_lab.freeze_trend_day_lists_v1 \
  --classification data/historical-evidence/day-trend-classification-90d-v1.json \
  --bullish-output data/historical-evidence/bullish-trend-days-90d-v1.txt \
  --bearish-output data/historical-evidence/bearish-trend-days-90d-v1.txt \
  --manifest-output data/historical-evidence/trend-day-lists-90d-v1-manifest.json
```

## Verify

```bash
echo "===== BULLISH ====="
cat data/historical-evidence/bullish-trend-days-90d-v1.txt

echo "===== BEARISH ====="
cat data/historical-evidence/bearish-trend-days-90d-v1.txt

echo "===== COUNTS ====="
wc -l \
  data/historical-evidence/bullish-trend-days-90d-v1.txt \
  data/historical-evidence/bearish-trend-days-90d-v1.txt
```

Expected counts from the current classifier run:
- 18 bullish
- 18 bearish

The frozen lists become the canonical input for the next OI persistence / directional-imbalance study.
