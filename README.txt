MIDPOINT V56 — ENABLE FAMILY E IN LIVE SHADOW

Selection:
- fresh Candidate A at boundary -> OTHER_FRESH_A, no B/E entry
- Candidate A false + mature VWAP -> E immediate shadow entry
- Candidate A false + not mature -> current B 10-minute watch

Shared management after B/E entry remains the V54 lifecycle.

Safety remains:
- observation_only=True
- execution_enabled=False
- paper_order_enabled=False
- quantity=None
- C/D/PM_E disabled

Run:

cd ~/RB-ITOS-AI
source .venv/bin/activate
export PYTHONPATH=backend

python scripts/apply_midpoint_v56_enable_family_e.py
python scripts/apply_midpoint_v56_enable_family_e.py --apply

python -m pytest tests/test_midpoint_v56_live_e_wiring.py -v
python -m pytest tests -q -k 'midpoint' --disable-warnings
python scripts/midpoint_v56_safety_smoke.py

Inspect git diff before restart.

Only after all tests pass:
scripts/restart.sh

Then confirm exactly one live-shadow worker and inspect Midpoint audit/status.
