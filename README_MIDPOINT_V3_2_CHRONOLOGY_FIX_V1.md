# Midpoint V3.2 Chronology Fix V1

This is a small correctness patch before the next research phase.

## 1. Exit-management module

In:

```text
backend/market_lab/midpoint_v3_2_exit_management_research_v1.py
```

add this field to each policy replay row:

```python
"entry_timestamp": trade.get("entry_timestamp"),
```

A reference patch is in:

```text
backend/market_lab/midpoint_v3_2_exit_management_research_v1_PATCH.txt
```

## 2. Validation module

In:

```text
backend/market_lab/midpoint_v3_2_frozen_exit_validation_v1.py
```

replace its `chronology_key()` with:

```python
from market_lab.midpoint_v3_2_chronology_fix_v1 import chronology_key
```

and, immediately after filtering the policy rows in `analyze()`, call:

```python
from market_lab.midpoint_v3_2_chronology_fix_v1 import validate_chronology_rows

validate_chronology_rows(rows)
```

## 3. Add helper + test

```text
backend/market_lab/midpoint_v3_2_chronology_fix_v1.py
tests/test_midpoint_v3_2_chronology_fix_v1.py
```

Run:

```bash
python -m pytest \
  tests/test_midpoint_v3_2_exit_management_research_v1.py \
  tests/test_midpoint_v3_2_frozen_exit_validation_v1.py \
  tests/test_midpoint_v3_2_chronology_fix_v1.py -v
```

Then rerun:

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

and:

```bash
python -m market_lab.midpoint_v3_2_frozen_exit_validation_v1 \
  --source data/historical-evidence/midpoint-v3-2-exit-management-research-v1-development.json \
  --output data/historical-evidence/midpoint-v3-2-frozen-exit-validation-v1-development.json
```
