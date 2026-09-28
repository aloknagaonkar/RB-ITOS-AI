MIDPOINT V57.1 — TERMINAL-CANDLE PARITY FIX

Run:

cd ~/RB-ITOS-AI
source .venv/bin/activate
export PYTHONPATH=backend

python scripts/apply_midpoint_v57_1_terminal_candle_parity_fix.py
python scripts/apply_midpoint_v57_1_terminal_candle_parity_fix.py --apply

python -m pytest tests/test_midpoint_v57_1_terminal_candle_parity.py -v
python -m pytest tests -q -k 'midpoint' --disable-warnings

Then rerun:

python scripts/midpoint_v57_full_historical_be_lifecycle_replay.py

cat data/historical-evidence/hilega-pcr-oi-support-research-v1/midpoint-v57-full-historical-be-lifecycle/summary-v57.txt

Do not restart live workers until all tests and V57 parity pass.
