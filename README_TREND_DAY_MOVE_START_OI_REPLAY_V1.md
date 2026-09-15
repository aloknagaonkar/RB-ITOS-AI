# Trend Day Move Start OI Replay V1

This produces the exact style of table requested, for every frozen bullish
and bearish day.

## Important definition

"Move start" is retrospective and price-only:

- bullish day = **last minimum 5-minute close** from 09:20 to 15:25
- bearish day = **last maximum 5-minute close** from 09:20 to 15:25

This is intentionally NOT a live signal. It is an objective anchor for studying
what OI looked like immediately before/at/after the dominant move.

Default replay:
- T-10
- T-5
- T0
- T+5
- T+10
- T+15
- T+20

At every checkpoint:
- ATM
- Moving ATM ±2
- Fixed 09:20 ATM ±2

Metrics:
- CE OI quantity change
- CE %
- PE OI quantity change
- PE %
- total activity
- PCR previous -> current

## Test

```bash
cd ~/RB-ITOS-AI
source .venv/bin/activate

python -m pytest tests/test_trend_day_move_start_oi_replay_v1.py -v
```

## Run

```bash
python -m market_lab.trend_day_move_start_oi_replay_v1 \
  --bullish-dates data/historical-evidence/bullish-trend-days-90d-v1.txt \
  --bearish-dates data/historical-evidence/bearish-trend-days-90d-v1.txt \
  --underlying 'TRAIN|data/historical-evidence/underlying-ohlc-train.csv' \
  --underlying 'OOS_A|data/historical-evidence/underlying-ohlc-oos-a.csv' \
  --underlying 'OOS_B|data/historical-evidence/underlying-ohlc-oos-b.csv' \
  --underlying 'OOS_C|data/historical-evidence/underlying-ohlc-oos-c.csv' \
  --underlying 'OOS_D|data/historical-evidence/underlying-ohlc-oos-d.csv' \
  --positioning 'TRAIN|data/historical-evidence/positioning-train.csv' \
  --positioning 'OOS_A|data/historical-evidence/positioning-oos-a.csv' \
  --positioning 'OOS_B|data/historical-evidence/positioning-oos-b.csv' \
  --positioning 'OOS_C|data/historical-evidence/positioning-oos-c.csv' \
  --positioning 'OOS_D|data/historical-evidence/positioning-oos-d.csv' \
  --fixed-atm-time 09:20 \
  --pre-minutes 10 \
  --post-minutes 20 \
  --output data/historical-evidence/trend-day-move-start-oi-replay-v1.json \
  --csv-output data/historical-evidence/trend-day-move-start-oi-replay-v1.csv
```

## Print all tables

```bash
python -m market_lab.trend_day_move_start_oi_replay_report_v1 \
  --input data/historical-evidence/trend-day-move-start-oi-replay-v1.json
```

## Bullish only

```bash
python -m market_lab.trend_day_move_start_oi_replay_report_v1 \
  --input data/historical-evidence/trend-day-move-start-oi-replay-v1.json \
  --class-filter BULLISH_TREND_DAY
```

## Bearish only

```bash
python -m market_lab.trend_day_move_start_oi_replay_report_v1 \
  --input data/historical-evidence/trend-day-move-start-oi-replay-v1.json \
  --class-filter BEARISH_TREND_DAY
```

The row prefixed with `*` is the retrospective move-start anchor.
