B FAMILY — V26 RUNNER DETERIORATION DIAGNOSTIC
================================================

Purpose
-------
Candle-by-candle descriptive analysis of the 11 frozen
RUNNER_STRENGTHENING events.

For every minute after classification, V26 records:
- directional close move
- directional favorable move
- running MFE
- drawdown from running MFE
- directional futures-VWAP diff
- VWAP change vs classification
- VWAP change vs prior minute
- milestone state (+50/+75/+100)

It also prints the first descriptive coincidence of:
- any drawdown + VWAP weakening
- drawdown >=10 + VWAP weakening
- drawdown >=20 + VWAP weakening

IMPORTANT:
10 and 20 are diagnostic labels only. They are NOT candidate exit thresholds.

Run:

cd ~/RB-ITOS-AI
source .venv/bin/activate
export PYTHONPATH=backend

python scripts/b_family_runner_deterioration_diagnostic_v26.py \
  | tee /tmp/b-family-runner-deterioration-v26.txt

Paste the complete output back.
