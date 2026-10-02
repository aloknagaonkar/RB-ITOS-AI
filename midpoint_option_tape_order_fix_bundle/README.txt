MIDPOINT OPTION TAPE CHRONOLOGY FIX

Place this folder in the RB-ITOS-AI repository root and run:

  cd ~/RB-ITOS-AI
  source .venv/bin/activate
  python midpoint_option_tape_order_fix_bundle/install.py

After PASS:

  ./scripts/restart.sh

Re-materialize today's file so its stored order is also chronological:

  PYTHONPATH=backend python -m \
    market_lab.midpoint_strategy.materialize_option_observation \
    --session-date 2026-10-01 \
    --expiry 2026-10-06

Expected printed order:

  2026-10-01T09:30:00+05:30 CE AVAILABLE 5 contracts
  2026-10-01T12:10:00+05:30 PE AVAILABLE 5 contracts

The API also sorts independently, so it selects PE after 12:10 even if a
previously saved JSON file was out of order.
