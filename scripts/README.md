# Opening Red + VWAP Validation v1

This is a dedicated follow-up to the VWAP overlay result where the opening-red structure showed better continuation/reclaim separation under bearish VWAP context.

## Input

The script consumes the output from the prior VWAP overlay:

```text
data/historical-evidence/
hilega-pcr-oi-support-research-v1/
vwap-overlay-research-v1/
opening-red-vwap-overlay-v1.csv
```

and the existing 180-session Nifty futures VWAP file:

```text
data/historical-evidence/
midpoint-v2-nifty-futures-vwap-v1-all180.csv
```

## What it tests

For each red midpoint/boundary-break event:

- below VWAP
- below VWAP + VWAP falling over 5m
- below VWAP + VWAP falling over 10m
- below VWAP + VWAP falling over 15m
- persistent below VWAP for 3m
- persistent below VWAP for 5m
- moving farther below VWAP over 5m
- recent downward VWAP cross/rejection
- below + falling + moving farther below
- distance below VWAP buckets

Outcomes remain:

```text
CONTINUATION
  BREAK_AND_GO
  BREAK_AND_BASE_THEN_GO

RECLAIM
  FALSE_BREAK_RECLAIM
```

## Chronological validation

The available red-event sessions are split chronologically:

```text
first 40 session dates  -> TRAIN
next 30                 -> VALIDATION
remaining dates         -> EVALUATION
```

This is descriptive validation, not a new trading rule.

## Run

Copy:

```text
opening_red_vwap_validation.py
```

to:

```text
~/RB-ITOS-AI/scripts/
```

Then:

```bash
cd ~/RB-ITOS-AI
source .venv/bin/activate
export PYTHONPATH=backend

python scripts/opening_red_vwap_validation.py \
  | tee /tmp/opening-red-vwap-validation.txt
```

## Outputs

```text
data/historical-evidence/
hilega-pcr-oi-support-research-v1/
opening-red-vwap-validation-v1/
```

Files:

- `opening-red-vwap-validation-events-v1.csv`
- `opening-red-vwap-validation-candidates-v1.csv`
- `opening-red-vwap-validation-summary-v1.txt`

Research only. No production rule, Hilega logic, or execution setting is changed.
