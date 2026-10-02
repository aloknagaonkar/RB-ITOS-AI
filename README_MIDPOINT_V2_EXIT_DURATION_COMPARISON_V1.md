# MIDPOINT V2 Exit Duration Comparison V1

This phase keeps V2 entry logic fixed and varies ONLY the time-exit rule.

## Frozen mechanics preserved

- initial stop: 5%
- breakeven trigger: +5%
- trailing activation: +10%
- trailing distance: 3%
- BE/trailing activate on the next bar
- gap-through stop exits at bar OPEN
- round-trip cost: 0.5 percentage points

These are identical across all policies.

## Policies

- `E15`: frozen V1-style hard 15-minute time exit
- `HYBRID`: at 15m exit unless trailing was already active; if active, continue trailing
- `E20`: hard 20-minute time exit
- `E30`: hard 30-minute time exit
- `TRAIL_ONLY`: no ordinary time exit; research safety cap at 60 minutes

The 60-minute cap is operational safety for finite replay, not a promoted trading rule.

## Test

```bash
cd ~/RB-ITOS-AI
source .venv/bin/activate

python -m pytest \
  tests/test_midpoint_v2_exit_duration_comparison_v1.py -v
```

## Run

```bash
python -m market_lab.midpoint_v2_exit_duration_comparison_v1 \
  --economics data/historical-evidence/midpoint-v2-new-arm-exact-option-economics-v1-development.json \
  --ohlc 'TRAIN|data/historical-evidence/option-ohlc-train.csv' \
  --ohlc 'OOS_A|data/historical-evidence/option-ohlc-oos-a.csv' \
  --ohlc 'OOS_B|data/historical-evidence/option-ohlc-oos-b.csv' \
  --ohlc 'OOS_C|data/historical-evidence/option-ohlc-oos-c.csv' \
  --ohlc 'OOS_D|data/historical-evidence/option-ohlc-oos-d.csv' \
  --output data/historical-evidence/midpoint-v2-exit-duration-comparison-v1-development.json
```

## Compact output

```bash
jq '{
  research_version,
  candidate_count,
  policies,
  frozen_exit_parameters,
  policy_summaries,
  policy_arm_summaries,
  integrity,
  governance
}' \
data/historical-evidence/midpoint-v2-exit-duration-comparison-v1-development.json
```

## Interpretation discipline

Do not automatically choose the numerically best policy from 17 trades.

First check:
- whether E15 reproduces the expected frozen-stop behavior;
- whether HYBRID actually extends only trades with an active trail;
- whether extension improves MFE capture without materially worsening downside;
- whether results are driven by one arm or one block;
- whether longer horizons merely increase exposure.

Any candidate policy still requires fresh OOS validation before V2 promotion.
