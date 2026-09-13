# Midpoint Failure Feature Diagnostics V2.1

Copy into the repo root.

Files:

```text
backend/market_lab/midpoint_failure_feature_diagnostics_v2_1.py
tests/test_midpoint_failure_feature_diagnostics_v2_1.py
docs/MIDPOINT_FAILURE_FEATURE_DIAGNOSTICS_V2_1.md
README_MIDPOINT_FAILURE_FEATURE_DIAGNOSTICS_V2_1.md
```

Test:

```bash
python -m pytest \
  tests/test_midpoint_failure_feature_diagnostics_v2_1.py -v
```

Run:

```bash
python -m market_lab.midpoint_failure_feature_diagnostics_v2_1 \
  --source data/historical-evidence/midpoint-break-strength-failure-v2-development.json \
  --output data/historical-evidence/midpoint-failure-feature-diagnostics-v2-1-development.json
```

Compact output:

```bash
jq '{
  research_version,
  feature_rankings_by_abs_median_gap,
  leakage_guard
}' data/historical-evidence/midpoint-failure-feature-diagnostics-v2-1-development.json
```

For the most useful pooled feature table:

```bash
jq '{
  bearish_t1: .pooled.BEARISH["T+1"],
  bearish_t3: .pooled.BEARISH["T+3"],
  bullish_t1: .pooled.BULLISH["T+1"],
  bullish_t3: .pooled.BULLISH["T+3"]
}' data/historical-evidence/midpoint-failure-feature-diagnostics-v2-1-development.json
```
