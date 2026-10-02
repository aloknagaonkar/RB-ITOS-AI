# Opening Candle Midpoint Reversal Framework V1

Copy this bundle into the root of `RB-ITOS-AI`.

Files:

```text
backend/market_lab/opening_candle_midpoint_framework_v1.py
tests/test_opening_candle_midpoint_framework_v1.py
docs/OPENING_CANDLE_MIDPOINT_REVERSAL_FRAMEWORK_V1.md
README_OPENING_CANDLE_MIDPOINT_FRAMEWORK_V1.md
```

Run tests:

```bash
python -m pytest \
  tests/test_opening_candle_midpoint_framework_v1.py -v
```

Run the 100-session symmetric research:

```bash
python -m market_lab.opening_candle_midpoint_framework_v1 \
  --block 'TRAIN|data/historical-evidence/underlying-ohlc-train.csv|data/historical-evidence/evidence-20.csv|data/historical-evidence/positioning-train.csv' \
  --block 'OOS_A|data/historical-evidence/underlying-ohlc-oos-a.csv|data/historical-evidence/evidence-oos.csv|data/historical-evidence/positioning-oos-a.csv' \
  --block 'OOS_B|data/historical-evidence/underlying-ohlc-oos-b.csv|data/historical-evidence/evidence-oos-b.csv|data/historical-evidence/positioning-oos-b.csv' \
  --block 'OOS_C|data/historical-evidence/underlying-ohlc-oos-c.csv|data/historical-evidence/evidence-oos-c.csv|data/historical-evidence/positioning-oos-c.csv' \
  --block 'OOS_D|data/historical-evidence/underlying-ohlc-oos-d.csv|data/historical-evidence/evidence-oos-d.csv|data/historical-evidence/positioning-oos-d.csv' \
  --output data/historical-evidence/opening-candle-midpoint-framework-v1-development.json
```
