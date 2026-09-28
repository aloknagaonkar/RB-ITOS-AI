MIDPOINT STRATEGY — SHADOW LIVE V1 / PHASE M1

This package is the additive first implementation step.

It intentionally does NOT guess the existing Hilega API/router/frontend file
paths. It creates the strategy module, safety contract, workspace contract and
Family-B management state machine first.

Copy files into the repo preserving paths.

Then run:

cd ~/RB-ITOS-AI
source .venv/bin/activate
export PYTHONPATH=backend

python scripts/midpoint_shadow_v1_smoke.py

Expected:
PASS: safety contract
PASS: Family B only
PASS: CAP20 rescue
PASS: one post-rescue re-entry
PASS: second re-entry blocked

Do NOT stage unrelated files.

Suggested staging after review:

git add   backend/market_lab/midpoint_strategy/__init__.py   backend/market_lab/midpoint_strategy/config.py   backend/market_lab/midpoint_strategy/models.py   backend/market_lab/midpoint_strategy/family_b_shadow.py   backend/market_lab/midpoint_strategy/workspace_contract.py   scripts/midpoint_shadow_v1_smoke.py   docs/MIDPOINT_STRATEGY_SHADOW_V1.md

The next phase is wiring this into the existing Hilega shared runtime/API/UI
after inspecting the current exact integration files.
