# Midpoint Confirm / Wait / Cancel State Machine V3

Files:

```text
backend/market_lab/midpoint_confirm_wait_cancel_state_machine_v3.py
tests/test_midpoint_confirm_wait_cancel_state_machine_v3.py
docs/MIDPOINT_CONFIRM_WAIT_CANCEL_STATE_MACHINE_V3.md
README_MIDPOINT_CONFIRM_WAIT_CANCEL_STATE_MACHINE_V3.md
```

Test:

```bash
python -m pytest \
  tests/test_midpoint_confirm_wait_cancel_state_machine_v3.py -v
```

Run:

```bash
python -m market_lab.midpoint_confirm_wait_cancel_state_machine_v3 \
  --source data/historical-evidence/midpoint-failure-diagnostics-v2-2-development.json \
  --output data/historical-evidence/midpoint-confirm-wait-cancel-state-machine-v3-development.json
```

Compact inspection:

```bash
jq '{
  research_version,
  design,
  quality,
  summary,
  leakage_guard
}' data/historical-evidence/midpoint-confirm-wait-cancel-state-machine-v3-development.json
```

Threshold inspection:

```bash
jq '.thresholds_train_only' \
  data/historical-evidence/midpoint-confirm-wait-cancel-state-machine-v3-development.json
```
