# Midpoint V3.2 False-Positive Diagnostics V1

Test:

```bash
python -m pytest \
  tests/test_midpoint_v3_2_false_positive_diagnostics_v1.py -v
```

Run:

```bash
python -m market_lab.midpoint_v3_2_false_positive_diagnostics_v1 \
  --state-machine data/historical-evidence/midpoint-stable-feature-state-machine-v3-2-development.json \
  --diagnostics data/historical-evidence/midpoint-failure-diagnostics-v2-2-development.json \
  --economics data/historical-evidence/midpoint-v3-2-exact-option-economics-v1-development.json \
  --output data/historical-evidence/midpoint-v3-2-false-positive-diagnostics-v1-development.json
```

Inspect:

```bash
jq '{
  research_version,
  confirmed_candidate_count,
  true_continuation_confirmed_count,
  false_positive_reversal_confirmed_count,
  confirm_precision_recomputed,
  true_confirmation_profile,
  false_positive_profile,
  t3_feature_comparison,
  economic_attribution,
  interpretation_guard,
  leakage_guard
}' data/historical-evidence/midpoint-v3-2-false-positive-diagnostics-v1-development.json
```

Details of the structural false positives:

```bash
jq '.false_positive_details' \
  data/historical-evidence/midpoint-v3-2-false-positive-diagnostics-v1-development.json
```
