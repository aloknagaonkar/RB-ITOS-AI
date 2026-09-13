# Midpoint decision V1 bundle

Copy this ZIP into the root of `RB-ITOS-AI`.

Files:
- `backend/market_lab/midpoint_trade_decision_research_v1.py`
- `backend/market_lab/midpoint_bullish_reclaim_research_v1.py`
- tests for both modules
- `docs/MIDPOINT_TRADE_DECISION_RESEARCH_V1.md`

Run tests:

```bash
python -m pytest \
  tests/test_midpoint_trade_decision_research_v1.py \
  tests/test_midpoint_bullish_reclaim_research_v1.py -v
```

Bearish decision run:

```bash
python -m market_lab.midpoint_trade_decision_research_v1 \
  --research data/historical-evidence/opening-red-midpoint-evidence-v1-1-development.json \
  --output data/historical-evidence/midpoint-trade-decision-v1-development.json
```

Bullish reclaim run:

```bash
python -m market_lab.midpoint_bullish_reclaim_research_v1 \
  --research data/historical-evidence/opening-red-midpoint-evidence-v1-1-development.json \
  --block 'TRAIN|data/historical-evidence/underlying-ohlc-train.csv|data/historical-evidence/evidence-20.csv|data/historical-evidence/positioning-train.csv' \
  --block 'OOS_A|data/historical-evidence/underlying-ohlc-oos-a.csv|data/historical-evidence/evidence-oos.csv|data/historical-evidence/positioning-oos-a.csv' \
  --block 'OOS_B|data/historical-evidence/underlying-ohlc-oos-b.csv|data/historical-evidence/evidence-oos-b.csv|data/historical-evidence/positioning-oos-b.csv' \
  --block 'OOS_C|data/historical-evidence/underlying-ohlc-oos-c.csv|data/historical-evidence/evidence-oos-c.csv|data/historical-evidence/positioning-oos-c.csv' \
  --block 'OOS_D|data/historical-evidence/underlying-ohlc-oos-d.csv|data/historical-evidence/evidence-oos-d.csv|data/historical-evidence/positioning-oos-d.csv' \
  --output data/historical-evidence/midpoint-bullish-reclaim-v1-development.json
```
