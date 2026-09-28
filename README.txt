MIDPOINT M2 — LIVE + HISTORICAL REPLAY UI

Implements:
- Midpoint live uses Hilega visual patterns as reference.
- Live Midpoint shows latest two AVAILABLE trading sessions only.
- Hilega Milega live backend also limits to latest two AVAILABLE session dates.
- Midpoint replay uses the SAME renderer as live.
- Replay sessions are materialized from parity-proven V57 data.
- Audit detail is lazy-loaded on Inspect.
- OTHER_FRESH_A displays as FRESH A with explanation.

Apply:
cd ~/RB-ITOS-AI
source .venv/bin/activate
export PYTHONPATH=backend
python scripts/apply_midpoint_m2_live_replay_ui.py

Test:
python -m pytest tests/test_midpoint_m2_live_replay_ui.py -v
python -m pytest tests -q -k 'midpoint' --disable-warnings

Materialize 3-session sample:
python scripts/midpoint_m2_materialize_historical_replay.py --limit 3

Then after API/frontend normal restart/build, validate UI.
If sample is good, materialize all tested sessions:
python scripts/midpoint_m2_materialize_historical_replay.py

Do NOT restart live_shadow_worker_v1 for this UI change.
