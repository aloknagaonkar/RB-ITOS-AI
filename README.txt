MIDPOINT V57 — FULL HISTORICAL B+E LIFECYCLE REPLAY

Run:

cd ~/RB-ITOS-AI
source .venv/bin/activate
export PYTHONPATH=backend

python -m pytest tests/test_midpoint_v57_replay_contract.py -v

python scripts/midpoint_v57_full_historical_be_lifecycle_replay.py

cat \
data/historical-evidence/hilega-pcr-oi-support-research-v1/\
midpoint-v57-full-historical-be-lifecycle/summary-v57.txt

Outputs:
- session-summary-v57.csv
- trade-lifecycle-v57.csv
- audit-events-v57.csv
- report-v57.json
- summary-v57.txt

Research-only: no live runtime mutation.
