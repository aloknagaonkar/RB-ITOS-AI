# Midpoint Four-Arm OI State Validation V1

Copy into the root of `RB-ITOS-AI`.

Files:

```text
backend/market_lab/midpoint_four_arm_oi_state_validation_v1.py
tests/test_midpoint_four_arm_oi_state_validation_v1.py
docs/MIDPOINT_FOUR_ARM_OI_STATE_VALIDATION_V1.md
README_MIDPOINT_FOUR_ARM_OI_STATE_VALIDATION_V1.md
```

Tests:

```bash
python -m pytest \
  tests/test_midpoint_four_arm_oi_state_validation_v1.py -v
```

Run:

```bash
python -m market_lab.midpoint_four_arm_oi_state_validation_v1 \
  --framework data/historical-evidence/opening-candle-midpoint-framework-v1-1-development.json \
  --decisions data/historical-evidence/midpoint-four-arm-decision-v1-development.json \
  --output data/historical-evidence/midpoint-four-arm-oi-state-validation-v1-development.json
```

Inspect:

```bash
jq '{
  research_version,
  promoted_primary_trade_now_oi_summary,
  arm_summaries,
  block_summaries,
  leakage_guard
}' data/historical-evidence/midpoint-four-arm-oi-state-validation-v1-development.json
```
