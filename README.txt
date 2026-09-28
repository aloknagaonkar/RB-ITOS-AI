MIDPOINT V62.2 — EXACT COORDINATOR ADAPTER

The inspected runtime shows the correct hook is inside
MidpointLiveShadowCoordinatorV1.process(), directly after _process_minute().

Safety:
- disabled by default
- no orders
- no B/E/CAP20/re-entry decision changes
- only observes new midpoint audit records and completed 1m underlying candles

Enable later with:
MIDPOINT_V62_OOS_COLLECTOR_ENABLED=1

Optional:
MIDPOINT_V62_OOS_LEDGER=<path>

Apply/test:

cd ~/RB-ITOS-AI
source .venv/bin/activate
export PYTHONPATH=backend

python scripts/apply_midpoint_v62_2_exact_coordinator_adapter.py
python scripts/verify_midpoint_v62_2_exact_coordinator_adapter.py

python -m pytest \
  tests/test_midpoint_v62_1_forward_oos_collector.py \
  tests/test_midpoint_v62_2_exact_coordinator_adapter.py -v

python -m pytest tests -q -k 'midpoint' --disable-warnings

DO NOT restart yet. Inspect git diff first.
