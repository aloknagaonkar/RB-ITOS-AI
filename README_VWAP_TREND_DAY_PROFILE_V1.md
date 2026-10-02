# VWAP Trend-Day Profile V1

Studies VWAP independently on the canonical 90-day price-only population: 18 bullish, 18 bearish, 54 mixed.

Chart timing is explicit: a 14:25 candle covers 14:25-14:29 and its close-vs-VWAP result is available at 14:30. Output reports both candle label and availability time.

Run:
```bash
cd ~/RB-ITOS-AI
source .venv/bin/activate
python -m pytest tests/test_vwap_trend_day_profile_v1.py -v
python -m market_lab.vwap_trend_day_profile_v1 \
  --classification data/historical-evidence/day-trend-classification-90d-v1.csv \
  --futures-vwap data/historical-evidence/midpoint-v2-nifty-futures-vwap-v1-development.csv \
  --output data/historical-evidence/vwap-trend-day-profile-v1.json \
  --csv-output data/historical-evidence/vwap-trend-day-profile-v1.csv
python -m market_lab.vwap_trend_day_profile_report_v1 \
  --input data/historical-evidence/vwap-trend-day-profile-v1.json
python -m market_lab.vwap_trend_day_profile_report_v1 \
  --input data/historical-evidence/vwap-trend-day-profile-v1.json --date 2026-08-25
python -m market_lab.vwap_trend_day_profile_report_v1 \
  --input data/historical-evidence/vwap-trend-day-profile-v1.json --date 2026-09-08
```
Research only; no V1/paper/live rule changes.
