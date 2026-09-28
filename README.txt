MIDPOINT MATURE-A-AT-BOUNDARY — V52.1 DETERMINISTIC ROBUSTNESS

Why V52.1
---------
V52 intentionally stopped because recursive repository-wide OHLC discovery found
millions of conflicting duplicate rows. V52.1 removes that ambiguity.

Deterministic sources
---------------------
B1 2024-08-16 -> 2025-02-05
  manifest:   data/historical-validation/manifest-b-v29-pre-v23-100.json
  underlying: data/historical-evidence/b-v29-pre-v23-100-underlying.csv
  futures:    data/historical-evidence/b-v29-pre-v23-100-futures-vwap.csv

B2 2025-02-06 -> 2025-07-16
  manifest:   data/historical-validation/manifest-b-v23-pre-v22-100.json
  underlying: data/historical-evidence/b-v23-pre-v22-100-underlying.csv
  futures:    data/historical-evidence/b-v23-pre-v22-100-futures-vwap.csv

B3 2025-07-17 -> 2025-12-11
  manifest:   data/historical-validation/manifest-b-v22-untouched-100.json
  underlying: data/historical-evidence/b-v22-untouched-100-underlying.csv
  futures:    data/historical-evidence/b-v22-untouched-100-futures-vwap.csv

B4 2025-12-12 -> 2026-09-08
  exact canonical loader:
  data/historical-evidence/underlying-ohlc-*.csv
  data/historical-evidence/midpoint-v2-nifty-futures-vwap-v1-all180.csv

Before using the structural builder on older blocks, V52.1 rebuilds B4 from raw
underlying and requires exact event parity with the canonical framework source.
Any mismatch stops the run.

Frozen research definition
--------------------------
At structural boundary T0:
- canonical fresh Candidate A is FALSE
- futures close - session VWAP is already directionally beyond +/-5
- no streak threshold
- no direction-specific tuning
- no exit tuning
- entry geometry starts at boundary-break close
- terminal is first adverse midpoint close or trusted 15:14 cutoff

Run
---
cd ~/RB-ITOS-AI
source .venv/bin/activate
export PYTHONPATH=backend

python scripts/midpoint_mature_boundary_robustness_v52_1.py

Then:
cat \
data/historical-evidence/hilega-pcr-oi-support-research-v1/\
midpoint-mature-boundary-robustness-v52_1/summary-v52_1.txt
