# Midpoint V3.2 Frozen Exit Validation V1

Test:

```bash
python -m pytest \
  tests/test_midpoint_v3_2_frozen_exit_validation_v1.py -v
```

Run:

```bash
python -m market_lab.midpoint_v3_2_frozen_exit_validation_v1 \
  --source data/historical-evidence/midpoint-v3-2-exit-management-research-v1-development.json \
  --output data/historical-evidence/midpoint-v3-2-frozen-exit-validation-v1-development.json
```

Compact result:

```bash
jq '{
  research_version,
  frozen_policy_id,
  promotion_status,
  train_summary,
  pooled_oos_a_d_summary,
  oos_block_summaries,
  direction_summaries,
  structural_false_positive_diagnostic,
  robustness_flags,
  governance,
  leakage_guard
}' data/historical-evidence/midpoint-v3-2-frozen-exit-validation-v1-development.json
```

Segments:

```bash
jq '.segments' \
  data/historical-evidence/midpoint-v3-2-frozen-exit-validation-v1-development.json
```
