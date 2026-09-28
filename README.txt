MIDPOINT V54 — SHARED B/E MANAGEMENT

Run:

cd ~/RB-ITOS-AI
source .venv/bin/activate
export PYTHONPATH=backend

1) Dry run:
python scripts/apply_midpoint_v54_shared_be_management.py

2) Apply:
python scripts/apply_midpoint_v54_shared_be_management.py --apply

3) Focused tests:
python -m pytest tests/test_midpoint_v54_shared_be_management.py -v

4) Existing Midpoint tests:
python -m pytest tests -q -k 'midpoint' --disable-warnings

5) Smoke:
python scripts/midpoint_v54_shared_management_smoke.py

6) Inspect:
git status --short
git diff --   backend/market_lab/midpoint_strategy/models.py   backend/market_lab/midpoint_strategy/config.py   backend/market_lab/midpoint_strategy/family_b_shadow.py   backend/market_lab/midpoint_strategy/runtime.py   tests/test_midpoint_v54_shared_be_management.py   scripts/midpoint_v54_shared_management_smoke.py

Do NOT restart the live worker in V54.
