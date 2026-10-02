# Trend Day OI Transition Template Discovery V1

Purpose: derive the common OI transition from the full frozen trend-day
population **before** testing any pattern across all 90 sessions.

Population:
- 18 frozen bullish trend days
- 18 frozen bearish trend days

Primary mode:
- Moving ATM ±2

Input:
- `trend-day-move-start-oi-replay-v1.json`

Relative sequence:
- T-10
- T-5
- T0
- T+5
- T+10
- T+15
- T+20

At every relative checkpoint the report includes:
- CE OI quantity change
- CE OI percentage change
- PE OI quantity change
- PE OI percentage change
- gross activity
- PEΔ - CEΔ imbalance
- positive/negative imbalance frequency
- PCR previous
- PCR current
- PCR change
- CE/PE sign-combination frequencies

For quantity, percentage, activity, imbalance and PCR the JSON keeps:
- q25
- median
- q75

This is template discovery only. It deliberately does NOT freeze a rule or
select a magnitude threshold.

## Test

```bash
cd ~/RB-ITOS-AI
source .venv/bin/activate

python -m pytest \
  tests/test_trend_day_oi_transition_template_discovery_v1.py -v
```

## Run

```bash
python -m market_lab.trend_day_oi_transition_template_discovery_v1 \
  --replay data/historical-evidence/trend-day-move-start-oi-replay-v1.json \
  --mode 'Moving ±2' \
  --output data/historical-evidence/trend-day-oi-transition-template-discovery-v1.json \
  --csv-output data/historical-evidence/trend-day-oi-transition-template-discovery-v1.csv
```

## Print the discovery table

```bash
python -m market_lab.trend_day_oi_transition_template_discovery_report_v1 \
  --input data/historical-evidence/trend-day-oi-transition-template-discovery-v1.json
```

After reviewing this output, the next step is to decide whether the evidence is
strong enough to define `BULLISH_OI_TEMPLATE_V1` and `BEARISH_OI_TEMPLATE_V1`.
Only then should the first-occurrence scanner be run against all 90 sessions.
