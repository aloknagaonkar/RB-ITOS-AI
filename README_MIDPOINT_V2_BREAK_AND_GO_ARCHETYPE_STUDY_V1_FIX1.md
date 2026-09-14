# FIX1 — Break-and-Go Archetype Study V1

Fixes:

`KeyError: 't3_timestamp'`

The frozen V3.2 state-machine event rows do not always persist `t3_timestamp`.
The exact-option-economics artifact does persist it for the same frozen event.

FIX1 now resolves T+3 in this order:

1. state row `t3_timestamp`, if present;
2. matching exact-option-economics row `t3_timestamp`;
3. mark underlying metrics unavailable with `MISSING_T3_TIMESTAMP`.

No timestamp is inferred from P&L or future price behavior.

Replace the original source and test files with this bundle.

Run:

```bash
cd ~/RB-ITOS-AI
source .venv/bin/activate

python -m pytest \
  tests/test_midpoint_v2_break_and_go_archetype_study_v1.py -v
```

Expected: 4 passed.

Then rerun the same study command.
