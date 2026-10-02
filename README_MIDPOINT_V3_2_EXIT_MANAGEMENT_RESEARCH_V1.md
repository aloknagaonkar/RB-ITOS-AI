# Midpoint V3.2 Exit Management Research V1

Test:

```bash
python -m pytest \
  tests/test_midpoint_v3_2_exit_management_research_v1.py -v
```

Run:

```bash
python -m market_lab.midpoint_v3_2_exit_management_research_v1 \
  --economics data/historical-evidence/midpoint-v3-2-exact-option-economics-v1-development.json \
  --block 'TRAIN|data/historical-evidence/option-ohlc-train.csv' \
  --block 'OOS_A|data/historical-evidence/option-ohlc-oos-a.csv' \
  --block 'OOS_B|data/historical-evidence/option-ohlc-oos-b.csv' \
  --block 'OOS_C|data/historical-evidence/option-ohlc-oos-c.csv' \
  --block 'OOS_D|data/historical-evidence/option-ohlc-oos-d.csv' \
  --output data/historical-evidence/midpoint-v3-2-exit-management-research-v1-development.json
```

Inspect:

```bash
jq '{
  research_version,
  train_only_nominated_policy,
  train_policy_ranking,
  policy_summaries,
  leakage_guard
}' data/historical-evidence/midpoint-v3-2-exit-management-research-v1-development.json
```
