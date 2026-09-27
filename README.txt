B FAMILY — INDEPENDENT HISTORICAL VALIDATION V6
=================================================

Goal
----
Validate the frozen B detector and current warning/recovery research on sessions
before the latest 60-session B/C/D development sample.

SAFETY / METHODOLOGY
--------------------
The script first performs a PARITY GATE:
- reconstruct B from raw 1m + futures VWAP;
- compare date/direction/timestamp against the known frozen 60-session B events;
- ABORT if parity is not exact.

Only after parity passes does it evaluate older sessions (< 2026-06-16).

Run
---
cd ~/RB-ITOS-AI
source .venv/bin/activate
export PYTHONPATH=backend

python scripts/b_family_independent_historical_validation_v6.py \
  | tee /tmp/b-family-independent-historical-validation-v6.txt

Outputs
-------
data/historical-evidence/hilega-pcr-oi-support-research-v1/
  b-family-independent-historical-validation-v6/
    b-family-parity-v6.csv
    b-family-independent-events-v6.csv
    b-family-independent-summary-v6.txt

Important
---------
- Do not bypass a failed parity gate.
- No runtime/execution changes.
- No new threshold tuning.
- 3-minute recovery candidate is evaluated unchanged.
- Underlying NIFTY points are not option premium P&L.
