# Candidate A Failure Diagnostics V1

Purpose: explain why frozen VWAP Candidate A succeeds or fails on the full 180-session midpoint framework.

This is **not** another threshold search.

It keeps Candidate A unchanged and compares continuation vs reclaim separately for:

- bearish Candidate A
- bullish mirrored Candidate A

Diagnostics include:

- directional distance from VWAP
- event time bucket
- age of most recent VWAP touch/cross condition
- directional VWAP movement over 5/10/15 minutes
- midpoint-to-boundary delay
- reference candle range
- complete reclaim/failure case listing

The buckets are fixed descriptive buckets; the script does not optimize them.

## Run

Copy `midpoint_vwap_candidate_a_failure_diagnostics.py` to `~/RB-ITOS-AI/scripts/`, then:

```bash
cd ~/RB-ITOS-AI
source .venv/bin/activate
export PYTHONPATH=backend

python scripts/midpoint_vwap_candidate_a_failure_diagnostics.py \
  | tee /tmp/midpoint-vwap-candidate-a-failure-diagnostics.txt
```

## Inputs

```text
data/historical-evidence/hilega-pcr-oi-support-research-v1/
midpoint-vwap-symmetric-180-validation-v1/
midpoint-vwap-symmetric-events-v1.csv

data/historical-evidence/
midpoint-v2-nifty-futures-vwap-v1-all180.csv
```

## Outputs

```text
data/historical-evidence/hilega-pcr-oi-support-research-v1/
midpoint-vwap-candidate-a-failure-diagnostics-v1/
```

Files:

- `candidate-a-event-diagnostics-v1.csv`
- `candidate-a-failures-v1.csv`
- `candidate-a-failure-diagnostics-summary-v1.txt`
