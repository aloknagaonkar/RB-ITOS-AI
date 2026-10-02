# VWAP 36 Trend-Day Examples V1

This joins the existing:

- `VWAP_TREND_DAY_PROFILE_V1`
- `TREND_DAY_MOVE_START_OI_REPLAY_V1`

for the frozen 36 trend days:

- 18 bullish
- 18 bearish

It prints one concrete, chart-validatable row per session.

## Important interpretation

`move_start` is the existing retrospective price-only last-minimum / last-maximum
anchor. It is useful for research alignment but is NOT a live signal.

VWAP candle state is causal:
- chart label 14:25 = interval starting 14:25
- that candle's close-vs-VWAP fact is available at 14:30

## Run

```bash
cd ~/RB-ITOS-AI
source .venv/bin/activate

python -m pytest tests/test_vwap_36_trend_day_examples_v1.py -v

python -m market_lab.vwap_36_trend_day_examples_v1 \
  --vwap-profile data/historical-evidence/vwap-trend-day-profile-v1.json \
  --move-replay data/historical-evidence/trend-day-move-start-oi-replay-v1.json \
  --output data/historical-evidence/vwap-36-trend-day-examples-v1.json \
  --csv-output data/historical-evidence/vwap-36-trend-day-examples-v1.csv

python -m market_lab.vwap_36_trend_day_examples_report_v1 \
  --input data/historical-evidence/vwap-36-trend-day-examples-v1.json
```

## Columns

- `Move`: retrospective dominant move-start candle
- `Pts`: move points from that anchor to the final 5m close
- `P3`: first aligned 3-checkpoint VWAP acceptance candle
- `P3Avail`: causal time when the P3 starting candle itself had closed
- `P3Lead`: minutes from that available time to the retrospective move-start
- `CrossP3`: first same-direction VWAP cross that later had 3-checkpoint acceptance
- `RunStart`: start of the aligned VWAP-side run containing the move-start anchor
- `Anchor`: ABOVE/BELOW at move-start
- `Dist`: futures close minus VWAP at move-start
- `Slope`: VWAP slope at move-start
- `Aligned`: whether VWAP side matched trend-day direction at move-start
