# Midpoint Failure Diagnostics V2.2

Files:

```text
backend/market_lab/midpoint_failure_diagnostics_v2_2.py
tests/test_midpoint_failure_diagnostics_v2_2.py
docs/MIDPOINT_FAILURE_DIAGNOSTICS_V2_2.md
README_MIDPOINT_FAILURE_DIAGNOSTICS_V2_2.md
```

Test:

```bash
python -m pytest \
  tests/test_midpoint_failure_diagnostics_v2_2.py -v
```

Run:

```bash
python -m market_lab.midpoint_failure_diagnostics_v2_2 \
  --source data/historical-evidence/midpoint-break-strength-failure-v2-development.json \
  --output data/historical-evidence/midpoint-failure-diagnostics-v2-2-development.json
```

First inspection:

```bash
jq '{
  research_version,
  corrections,
  coverage,
  feature_rankings_by_abs_median_gap,
  leakage_guard
}' data/historical-evidence/midpoint-failure-diagnostics-v2-2-development.json
```

Then inspect corrected pooled evidence:

```bash
jq '{
  bearish_t1: .pooled.BEARISH["T+1"],
  bearish_t3: .pooled.BEARISH["T+3"],
  bullish_t1: .pooled.BULLISH["T+1"],
  bullish_t3: .pooled.BULLISH["T+3"]
}' data/historical-evidence/midpoint-failure-diagnostics-v2-2-development.json
```
