# Midpoint V3.2 Temporal Stability and Uncertainty V1

Test:

```bash
python -m pytest \
  tests/test_midpoint_v3_2_temporal_stability_and_uncertainty_v1.py -v
```

Run:

```bash
python -m market_lab.midpoint_v3_2_temporal_stability_and_uncertainty_v1 \
  --source data/historical-evidence/midpoint-v3-2-exit-management-research-v1-development.json \
  --output data/historical-evidence/midpoint-v3-2-temporal-stability-and-uncertainty-v1-development.json
```

Compact result:

```bash
jq '{
  research_version,
  frozen_policy_id,
  promotion_status,
  headline,
  bootstrap_uncertainty,
  train_vs_oos_permutation_diagnostic,
  leave_one_oos_block_out,
  calendar_month_summaries,
  rolling_all_development: .rolling_all_development.summary,
  rolling_oos_a_d: .rolling_oos_a_d.summary,
  composition_vs_within_segment,
  interpretation_guard,
  leakage_guard
}' data/historical-evidence/midpoint-v3-2-temporal-stability-and-uncertainty-v1-development.json
```

Further detail:

```bash
jq '.leave_one_month_out_all_development' \
  data/historical-evidence/midpoint-v3-2-temporal-stability-and-uncertainty-v1-development.json
```

```bash
jq '.rolling_all_development.windows' \
  data/historical-evidence/midpoint-v3-2-temporal-stability-and-uncertainty-v1-development.json
```
