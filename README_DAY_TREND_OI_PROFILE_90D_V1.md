# Day Trend + OI Profile 90D V1

This bundle implements the research order we agreed on:

1. classify the latest 90 sessions using **price only**;
2. select strongest bullish and bearish trend days;
3. evaluate Moving ATM ±2 OI only on those selected dates.

No current day. No DB. No OOS E/F/G/H.

## Step 1 — tests

```bash
cd ~/RB-ITOS-AI
source .venv/bin/activate

python -m pytest \
  tests/test_day_trend_classification_90d_v1.py \
  tests/test_oi_pm2_trend_day_profile_v1.py -v
```

## Step 2 — classify 90 days

```bash
python -m market_lab.day_trend_classification_90d_v1 \
  --underlying 'TRAIN|data/historical-evidence/underlying-ohlc-train.csv' \
  --underlying 'OOS_A|data/historical-evidence/underlying-ohlc-oos-a.csv' \
  --underlying 'OOS_B|data/historical-evidence/underlying-ohlc-oos-b.csv' \
  --underlying 'OOS_C|data/historical-evidence/underlying-ohlc-oos-c.csv' \
  --underlying 'OOS_D|data/historical-evidence/underlying-ohlc-oos-d.csv' \
  --latest-sessions 90 \
  --extreme-fraction 0.20 \
  --output data/historical-evidence/day-trend-classification-90d-v1.json \
  --csv-output data/historical-evidence/day-trend-classification-90d-v1.csv
```

This should select about 18 strongest bullish and 18 strongest bearish sessions.
The middle sessions remain MIXED_DAY.

## Step 3 — evaluate Moving ATM ±2 on those selected dates

```bash
python -m market_lab.oi_pm2_trend_day_profile_v1 \
  --classification data/historical-evidence/day-trend-classification-90d-v1.json \
  --positioning 'TRAIN|data/historical-evidence/positioning-train.csv' \
  --positioning 'OOS_A|data/historical-evidence/positioning-oos-a.csv' \
  --positioning 'OOS_B|data/historical-evidence/positioning-oos-b.csv' \
  --positioning 'OOS_C|data/historical-evidence/positioning-oos-c.csv' \
  --positioning 'OOS_D|data/historical-evidence/positioning-oos-d.csv' \
  --output data/historical-evidence/oi-pm2-trend-day-profile-v1.json \
  --csv-output data/historical-evidence/oi-pm2-trend-day-profile-v1.csv
```

Important interpretation:
- trend-day labels are created from price only;
- OI is evaluated after the dates are frozen;
- both OI quantity and OI percentage are preserved;
- Moving ATM ±2 is the primary band;
- output is descriptive research, not a trading rule.
