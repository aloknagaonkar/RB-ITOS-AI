# MIDPOINT_OI_QUANTITY_THRESHOLD_DIAGNOSTICS_V1

Purpose:
Validate whether an apparently large OI percentage move is meaningful only when
the absolute OI quantity/change is also large enough.

This specifically addresses the problem:

> A small OI base can produce a large percentage change, even though the actual
> number of contracts added/removed is small.

The experiment uses the already-created 159-row development feature CSV.

It studies:

- current overall ATM CE+PE OI
- ATM absolute CE/PE OI change over 5 minutes
- total ATM absolute OI activity
- ATM±2 total OI
- ATM±2 absolute OI activity
- large-% + large-quantity
- large-% + small-quantity
- small-% + large-quantity
- small-% + small-quantity
- bullish and bearish separately

No fixed trading threshold is selected. Quartiles are descriptive.

## Test

```bash
cd ~/RB-ITOS-AI
source .venv/bin/activate

python -m pytest \
  tests/test_midpoint_oi_quantity_threshold_diagnostics_v1.py -v
```

## Run

```bash
python -m market_lab.midpoint_oi_quantity_threshold_diagnostics_v1 \
  --features data/historical-evidence/midpoint-oi-magnitude-features-v1-development.csv \
  --output data/historical-evidence/midpoint-oi-quantity-threshold-diagnostics-v1-development.json
```
