# MIDPOINT_V3_2_TEMPORAL_DEPENDENCE_ROBUSTNESS_V1

Research-only temporal-dependence robustness diagnostics for the already-frozen:

- Entry: `MIDPOINT_STABLE_FEATURE_STATE_MACHINE_V3_2`
- Exit: `SL5_BE5_TRAIL3_AFTER10_TIME15`

## Scope

This phase **does not** change the strategy.

It uses only:

- `TRAIN`
- `OOS_A`
- `OOS_B`
- `OOS_C`
- `OOS_D`

It explicitly rejects frozen-policy rows from `OOS_E`, `OOS_F`, `OOS_G`, or `OOS_H`.

`OOS_H` remains pristine.

## Analyses

1. Calendar-month cluster bootstrap
2. OOS-block cluster bootstrap
3. Circular moving-block bootstrap with 3, 5, and 10 trade blocks
4. Worst observed month frequency stress at 2x and 3x
5. Chronological rolling stability at 10, 15, and 20 trades
6. Descriptive robustness assessment

None of these outputs is permission to add a filter or promote the strategy.

## Install

Copy:

```text
backend/market_lab/midpoint_v3_2_temporal_dependence_robustness_v1.py
tests/test_midpoint_v3_2_temporal_dependence_robustness_v1.py
docs/MIDPOINT_V3_2_TEMPORAL_DEPENDENCE_ROBUSTNESS_V1.md
README_MIDPOINT_V3_2_TEMPORAL_DEPENDENCE_ROBUSTNESS_V1.md
```

into the corresponding repo paths.

## Test

```bash
cd ~/RB-ITOS-AI
source .venv/bin/activate

python -m pytest \
  tests/test_midpoint_v3_2_temporal_dependence_robustness_v1.py -v
```

## Run

```bash
python -m market_lab.midpoint_v3_2_temporal_dependence_robustness_v1 \
  --source data/historical-evidence/midpoint-v3-2-exit-management-research-v1-development.json \
  --output data/historical-evidence/midpoint-v3-2-temporal-dependence-robustness-v1-development.json \
  --bootstrap-iterations 20000 \
  --seed 42
```

## Recommended compact inspection

```bash
jq '{
  research_version,
  frozen_policy_id,
  promotion_status,
  headline,
  month_cluster_bootstrap_oos_a_d,
  oos_block_cluster_bootstrap,
  moving_block_bootstrap_oos_a_d,
  worst_regime_stress_oos_a_d,
  chronological_stability_oos_a_d,
  research_assessment,
  interpretation_guard,
  leakage_guard
}' \
data/historical-evidence/midpoint-v3-2-temporal-dependence-robustness-v1-development.json
```

Send the test output and compact JSON output back for interpretation before touching OOS-H.
