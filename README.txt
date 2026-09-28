MIDPOINT V55 — B/E BOUNDARY CLASSIFIER + REPLAY PARITY

Install/copy these files into the repo, then:

cd ~/RB-ITOS-AI
source .venv/bin/activate
export PYTHONPATH=backend

python -m pytest tests/test_midpoint_v55_boundary_classifier.py -v

python scripts/midpoint_v55_boundary_selection_replay.py

cat \
data/historical-evidence/hilega-pcr-oi-support-research-v1/\
midpoint-boundary-classifier-v55/summary-v55.txt

Then run existing Midpoint tests:

python -m pytest tests -q -k 'midpoint' --disable-warnings

V55 does not modify live_shadow_v1.py.
Do not restart live workers for V55.
