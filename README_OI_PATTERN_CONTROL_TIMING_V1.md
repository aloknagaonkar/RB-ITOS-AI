# OI Pattern Control + Candle Timing V1

This study answers the requested next questions without freezing quantity thresholds.

## What it tests

Across the 90-session TRAIN + OOS_A-D development universe:

- 18 frozen bullish trend days
- 18 frozen bearish trend days
- remaining sessions become mixed/control days

It causally scans completed 5-minute candles for:

### Bullish candidate
- previous Moving ATM ±2 5m imbalance <= 0
- current Moving ATM ±2 5m imbalance > 0
- current 5m PCR change > 0
- fixed-09:20 session imbalance improved from previous checkpoint

### Bearish candidate
Exact mirror.

No OI quantity threshold is applied yet.

## What it reports

For every day:
- first bullish detection candle time
- first bearish detection candle time
- how many fresh bullish patterns appeared
- how many fresh bearish patterns appeared

For every detected occurrence:
- exact completed candle time
- spot close
- moving ATM
- CE/PE 5m OI quantity changes
- 5m imbalance
- 5m PCR change
- CE/PE OI added today since 09:20
- session imbalance
- session PCR change
- whether the pattern persists 2/3/4 checkpoints
- directional price move after +5/+10/+15/+20 minutes

This makes manual TradingView/chart validation possible.

## Test

```bash
cd ~/RB-ITOS-AI
source .venv/bin/activate
python -m pytest tests/test_oi_pattern_control_timing_v1.py -v
```

## Run

```bash
python -m market_lab.oi_pattern_control_timing_v1 \
  --bullish-dates data/historical-evidence/bullish-trend-days-90d-v1.txt \
  --bearish-dates data/historical-evidence/bearish-trend-days-90d-v1.txt \
  --positioning 'TRAIN|data/historical-evidence/positioning-train.csv' \
  --positioning 'OOS_A|data/historical-evidence/positioning-oos-a.csv' \
  --positioning 'OOS_B|data/historical-evidence/positioning-oos-b.csv' \
  --positioning 'OOS_C|data/historical-evidence/positioning-oos-c.csv' \
  --positioning 'OOS_D|data/historical-evidence/positioning-oos-d.csv' \
  --output data/historical-evidence/oi-pattern-control-timing-v1.json \
  --csv-output data/historical-evidence/oi-pattern-control-timing-v1.csv
```

## Report

```bash
python -m market_lab.oi_pattern_control_timing_report_v1 \
  --input data/historical-evidence/oi-pattern-control-timing-v1.json
```

## Interpretation

The `Candle` column is the completed 5-minute candle where the causal OI state
first flips into the candidate bullish/bearish condition. Example: `13:50`
means information from the completed 13:50 checkpoint, not future bars.

`Bull#` / `Bear#` count fresh sign-transition occurrences during that day.
Persistent continuation after one flip is not counted repeatedly as another pattern.

Do not freeze a quantity threshold from this output alone. Compare trend classes
against mixed/control days and then assess block stability.
