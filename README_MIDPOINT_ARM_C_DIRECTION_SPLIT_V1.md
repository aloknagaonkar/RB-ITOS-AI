# MIDPOINT_ARM_C_DIRECTION_SPLIT_V1

Descriptive-only split of the existing Arm C controlled-comparison population into BULLISH and BEARISH trades.

This does **not** change Arm C and does **not** promote a direction filter.

## Run

```bash
cd ~/RB-ITOS-AI
source .venv/bin/activate

python -m pytest \
  tests/test_midpoint_arm_c_direction_split_v1.py -v

python -m market_lab.midpoint_arm_c_direction_split_v1 \
  --comparison data/historical-evidence/midpoint-oi-vwap-controlled-comparison-v1-development.json \
  --output data/historical-evidence/midpoint-arm-c-direction-split-v1-development.json
```

Inspect:

```bash
jq '{
  population,
  bullish,
  bearish,
  bearish_minus_bullish,
  by_block,
  integrity,
  interpretation_guard
}' \
data/historical-evidence/midpoint-arm-c-direction-split-v1-development.json
```

Decision rule for research interpretation:
- If one side is better overall but unstable by block, treat it as a hypothesis only.
- If one side is consistently stronger across blocks and horizons, freeze that observation and test it on fresh precommitted OOS.
- Do not tune thresholds from this split.
