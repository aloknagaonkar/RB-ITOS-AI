# Midpoint V3.2 TRAIN-vs-OOS Regime Stability V1

Files:

```text
backend/market_lab/midpoint_v3_2_train_oos_regime_stability_v1.py
tests/test_midpoint_v3_2_train_oos_regime_stability_v1.py
docs/MIDPOINT_V3_2_TRAIN_OOS_REGIME_STABILITY_V1.md
README_MIDPOINT_V3_2_TRAIN_OOS_REGIME_STABILITY_V1.md
```

Test:

```bash
python -m pytest \
  tests/test_midpoint_v3_2_train_oos_regime_stability_v1.py -v
```

Run:

```bash
python -m market_lab.midpoint_v3_2_train_oos_regime_stability_v1 \
  --source data/historical-evidence/midpoint-v3-2-exit-management-research-v1-development.json \
  --output data/historical-evidence/midpoint-v3-2-train-oos-regime-stability-v1-development.json
```

Compact result:

```bash
jq '{
  research_version,
  frozen_policy_id,
  train_summary,
  pooled_oos_a_d_summary,
  block_summaries,
  interpretation_guard,
  leakage_guard
}' data/historical-evidence/midpoint-v3-2-train-oos-regime-stability-v1-development.json
```

Detailed dimension analysis:

```bash
jq '.dimension_analysis' \
  data/historical-evidence/midpoint-v3-2-train-oos-regime-stability-v1-development.json
```
