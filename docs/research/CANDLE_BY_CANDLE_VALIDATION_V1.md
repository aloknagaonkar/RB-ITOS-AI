
# CANDLE_BY_CANDLE_VALIDATION_V1

Generic research-only reporter.

This tool does **not** create a new trading rule or regime state machine.
It reformats an existing `OI_PRICE_REGIME_TRANSITION_AUDIT_V1_1` JSON into
a date-generic candle-by-candle validation report.

Every candle preserves two distinct option-OI views:

1. **Recent OI — moving ATM ±5**
   - current ATM is detected at time T
   - those exact 11 physical strikes are compared at T vs T-5/T-10/T-15

2. **Session OI — fixed 09:20 ATM ±5**
   - the 09:20 ATM is frozen
   - those exact 11 morning strikes are compared from 09:20 to current time T

The report also includes:
- futures price 5m/10m/15m
- futures OI status
- corrected same-strike PCR
- VWAP
- existing P1/P2 strategy events
- optional retrospective evaluation label

## Usage after running V1.1

```bash
python -m market_lab.candle_by_candle_validation_v1 \
  --audit-json data/historical-evidence/oi-price-regime-audit-2026-08-25-v1-1.json \
  --csv data/historical-evidence/candle-validation-2026-08-25-v1.csv \
  --text-output data/historical-evidence/candle-validation-2026-08-25-v1.txt
```

Use the same command for any date by changing the input/output date.
