# Four-arm midpoint decision research V1

Copy this bundle into the root of `RB-ITOS-AI`.

Files:

```text
backend/market_lab/midpoint_four_arm_decision_research_v1.py
tests/test_midpoint_four_arm_decision_research_v1.py
docs/MIDPOINT_FOUR_ARM_DECISION_RESEARCH_V1.md
README_MIDPOINT_FOUR_ARM_DECISION_V1.md
```

Run tests:

```bash
python -m pytest \
  tests/test_midpoint_four_arm_decision_research_v1.py -v
```

Run research:

```bash
python -m market_lab.midpoint_four_arm_decision_research_v1 \
  --framework data/historical-evidence/opening-candle-midpoint-framework-v1-1-development.json \
  --output data/historical-evidence/midpoint-four-arm-decision-v1-development.json
```

Inspect compact result:

```bash
jq '{
  research_version,
  compact_summary,
  leakage_guard,
  next_phase_gate
}' data/historical-evidence/midpoint-four-arm-decision-v1-development.json
```
