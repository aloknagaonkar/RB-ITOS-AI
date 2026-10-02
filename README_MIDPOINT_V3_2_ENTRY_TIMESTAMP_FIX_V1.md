# Midpoint V3.2 entry_timestamp fix V1

The regime-stability module failed because the exit-management JSON rows did not
actually contain `entry_timestamp`.

The previous chronology helper was present and its unit tests passed, but the
existing exit-management module itself had not been modified to propagate:

```python
"entry_timestamp": trade.get("entry_timestamp"),
```

This bundle contains complete corrected files, not patch instructions.

Replace these files:

```text
backend/market_lab/midpoint_v3_2_exit_management_research_v1.py
backend/market_lab/midpoint_v3_2_frozen_exit_validation_v1.py
backend/market_lab/midpoint_v3_2_chronology_fix_v1.py
backend/market_lab/midpoint_v3_2_train_oos_regime_stability_v1.py
tests/test_midpoint_v3_2_entry_timestamp_fix_v1.py
```

Run tests:

```bash
python -m pytest \
  tests/test_midpoint_v3_2_exit_management_research_v1.py \
  tests/test_midpoint_v3_2_frozen_exit_validation_v1.py \
  tests/test_midpoint_v3_2_chronology_fix_v1.py \
  tests/test_midpoint_v3_2_train_oos_regime_stability_v1.py \
  tests/test_midpoint_v3_2_entry_timestamp_fix_v1.py -v
```

Regenerate the exit-management JSON FIRST:

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

Verify timestamps are present:

```bash
jq '[.rows[] | select(.policy_id=="SL5_BE5_TRAIL3_AFTER10_TIME15") | .entry_timestamp] | {count:length, missing:map(select(.==null))|length, first:.[0]}' \
  data/historical-evidence/midpoint-v3-2-exit-management-research-v1-development.json
```

Expected:

```text
count: 77
missing: 0
first: <ISO timestamp>
```

Then rerun frozen validation and regime stability.
