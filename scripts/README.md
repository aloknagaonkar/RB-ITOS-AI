# Midpoint + VWAP Symmetric 180-Session Validation v1

This validates the frozen VWAP Candidate A symmetrically:

```text
Bearish RED:
event >5 futures points below VWAP
AND prior 5m touched/approached VWAP within 5 points or above.

Bullish GREEN mirror:
event >5 futures points above VWAP
AND prior 5m touched/approached VWAP within 5 points or below.
```

It also reports the already-frozen **18 bullish + 18 bearish directional sessions** separately.

## Important methodology

The 36 directional sessions are **not assumed to produce 100%**. The script measures the actual result. If they do produce 100%, that will be reported; if not, the exceptions are important evidence rather than something to tune away.

The script uses only existing exact `OPENING_CANDLE_MIDPOINT_REVERSAL_FRAMEWORK_V1_1` event artifacts. It will automatically discover:

```text
data/historical-evidence/opening-candle-midpoint-framework-v1-1*.json
```

It intentionally refuses to invent missing midpoint events from futures VWAP.

This matters because the original framework semantics are:

```text
ignore 09:15–09:19
first valid later RED / GREEN structure
1-minute CLOSE midpoint crossing
1-minute CLOSE boundary crossing
```

The VWAP overlay is joined only after those original structural events exist.

## Run

Copy:

```text
midpoint_vwap_symmetric_180_validation.py
```

to:

```text
~/RB-ITOS-AI/scripts/
```

Then run:

```bash
cd ~/RB-ITOS-AI
source .venv/bin/activate
export PYTHONPATH=backend

python scripts/midpoint_vwap_symmetric_180_validation.py \
  | tee /tmp/midpoint-vwap-symmetric-180.txt
```

## Outputs

```text
data/historical-evidence/
hilega-pcr-oi-support-research-v1/
midpoint-vwap-symmetric-180-validation-v1/
```

The script reports:

- bearish Candidate A vs NOT A
- bullish mirrored Candidate A vs NOT A
- combined
- frozen 36 expected-direction events
- frozen 36 counter-direction control
- exact framework session coverage

If framework coverage is currently below 180, the output says exactly how many sessions are covered and does not silently substitute a different event-generation method.
