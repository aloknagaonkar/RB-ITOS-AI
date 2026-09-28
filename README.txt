MIDPOINT STRATEGY — M3B.1 CANONICAL PARITY

DO NOT enable MIDPOINT_SHADOW_ENABLED yet.

cd ~/RB-ITOS-AI
source .venv/bin/activate
export PYTHONPATH=backend

1) Dry run:
python scripts/apply_midpoint_m3b_1_canonical_parity.py

2) Apply:
python scripts/apply_midpoint_m3b_1_canonical_parity.py --apply

3) Tests:
python -m pytest \
  tests/test_midpoint_m3b_1_canonical_parity.py \
  tests/test_midpoint_m3b_live_shadow_v1.py \
  tests/test_midpoint_m2_auditable_runtime.py \
  tests/test_midpoint_m3_live_shadow_ui.py \
  tests/test_midpoint_m3_1_query_defaults.py -v

4) Existing synthetic smoke:
python scripts/midpoint_m3b_smoke.py

5) Strict 2026-08-25 parity:
python scripts/midpoint_m3b_1_aug25_parity.py

Expected known parity:
- bearish boundary 09:39
- bearish B entry 09:42
- delay 3 minutes
- exact reference high/midpoint/low
- exact canonical raw futures-VWAP diff
- no nearest-minute substitution
- no interpolation

Keep MIDPOINT_SHADOW_ENABLED=0.
Do not restart the live worker.
Do not use git add .
Do not stage *.pre-midpoint-m3b1.bak.
