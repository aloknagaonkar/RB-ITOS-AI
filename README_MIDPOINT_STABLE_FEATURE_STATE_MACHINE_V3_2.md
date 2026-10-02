# Midpoint Stable-Feature State Machine V3.2

Files:

```text
backend/market_lab/midpoint_stable_feature_state_machine_v3_2.py
tests/test_midpoint_stable_feature_state_machine_v3_2.py
docs/MIDPOINT_STABLE_FEATURE_STATE_MACHINE_V3_2.md
README_MIDPOINT_STABLE_FEATURE_STATE_MACHINE_V3_2.md
```

Test:

```bash
python -m pytest \
  tests/test_midpoint_stable_feature_state_machine_v3_2.py -v
```

Run:

```bash
python -m market_lab.midpoint_stable_feature_state_machine_v3_2 \
  --source data/historical-evidence/midpoint-failure-diagnostics-v2-2-development.json \
  --output data/historical-evidence/midpoint-stable-feature-state-machine-v3-2-development.json
```

Compact inspection:

```bash
jq '{
  research_version,
  design,
  quality,
  summary,
  leakage_guard
}' data/historical-evidence/midpoint-stable-feature-state-machine-v3-2-development.json
```

Inspect TRAIN-only stable feature activation:

```bash
jq '.t3_train_only_rules' \
  data/historical-evidence/midpoint-stable-feature-state-machine-v3-2-development.json
```
