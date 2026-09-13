# Midpoint V3.2 Exact Option Economics V1

Files:

```text
backend/market_lab/midpoint_v3_2_exact_option_economics_v1.py
tests/test_midpoint_v3_2_exact_option_economics_v1.py
docs/MIDPOINT_V3_2_EXACT_OPTION_ECONOMICS_V1.md
README_MIDPOINT_V3_2_EXACT_OPTION_ECONOMICS_V1.md
```

Test:

```bash
python -m pytest \
  tests/test_midpoint_v3_2_exact_option_economics_v1.py -v
```

Run:

```bash
python -m market_lab.midpoint_v3_2_exact_option_economics_v1 \
  --state-machine data/historical-evidence/midpoint-stable-feature-state-machine-v3-2-development.json \
  --diagnostics data/historical-evidence/midpoint-failure-diagnostics-v2-2-development.json \
  --block 'TRAIN|data/historical-evidence/positioning-train.csv|data/historical-evidence/option-ohlc-train.csv' \
  --block 'OOS_A|data/historical-evidence/positioning-oos-a.csv|data/historical-evidence/option-ohlc-oos-a.csv' \
  --block 'OOS_B|data/historical-evidence/positioning-oos-b.csv|data/historical-evidence/option-ohlc-oos-b.csv' \
  --block 'OOS_C|data/historical-evidence/positioning-oos-c.csv|data/historical-evidence/option-ohlc-oos-c.csv' \
  --block 'OOS_D|data/historical-evidence/positioning-oos-d.csv|data/historical-evidence/option-ohlc-oos-d.csv' \
  --output data/historical-evidence/midpoint-v3-2-exact-option-economics-v1-development.json
```

Compact inspection:

```bash
jq '{
  research_version,
  entry_rule,
  contract_rule,
  confirmed_candidate_count,
  missing_t3_timestamp_count,
  overall_summary,
  direction_summaries,
  block_summaries,
  leakage_guard
}' data/historical-evidence/midpoint-v3-2-exact-option-economics-v1-development.json
```

Segment inspection:

```bash
jq '.segments' \
  data/historical-evidence/midpoint-v3-2-exact-option-economics-v1-development.json
```
