# Midpoint Confirm / Wait / Cancel State Machine V3.1

Files:

```text
backend/market_lab/midpoint_confirm_wait_cancel_state_machine_v3_1.py
tests/test_midpoint_confirm_wait_cancel_state_machine_v3_1.py
docs/MIDPOINT_CONFIRM_WAIT_CANCEL_STATE_MACHINE_V3_1.md
README_MIDPOINT_CONFIRM_WAIT_CANCEL_STATE_MACHINE_V3_1.md
```

Test:

```bash
python -m pytest \
  tests/test_midpoint_confirm_wait_cancel_state_machine_v3_1.py -v
```

Run:

```bash
python -m market_lab.midpoint_confirm_wait_cancel_state_machine_v3_1 \
  --source data/historical-evidence/midpoint-failure-diagnostics-v2-2-development.json \
  --output data/historical-evidence/midpoint-confirm-wait-cancel-state-machine-v3-1-development.json
```

Compact inspection:

```bash
jq '{
  research_version,
  corrections_over_v3,
  quality,
  summary,
  leakage_guard
}' data/historical-evidence/midpoint-confirm-wait-cancel-state-machine-v3-1-development.json
```

Threshold/polarity inspection:

```bash
jq '.thresholds_train_only' \
  data/historical-evidence/midpoint-confirm-wait-cancel-state-machine-v3-1-development.json
```
