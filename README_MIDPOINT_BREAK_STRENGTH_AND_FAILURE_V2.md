# Midpoint Break Strength and Failure V2

Files:
```text
backend/market_lab/midpoint_break_strength_failure_v2.py
tests/test_midpoint_break_strength_failure_v2.py
docs/MIDPOINT_BREAK_STRENGTH_AND_FAILURE_V2.md
README_MIDPOINT_BREAK_STRENGTH_AND_FAILURE_V2.md
```

Test:
```bash
python -m pytest tests/test_midpoint_break_strength_failure_v2.py -v
```

Run:
```bash
python -m market_lab.midpoint_break_strength_failure_v2 \
  --framework data/historical-evidence/opening-candle-midpoint-framework-v1-1-development.json \
  --output data/historical-evidence/midpoint-break-strength-failure-v2-development.json
```

Inspect:
```bash
jq '{
  research_version,
  checkpoints,
  oi_states_included,
  strong_oi_definitions,
  explicit_reversal_oi_definitions,
  summary,
  leakage_guard
}' data/historical-evidence/midpoint-break-strength-failure-v2-development.json
```
