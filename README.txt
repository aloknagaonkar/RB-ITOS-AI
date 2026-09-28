MIDPOINT V62.1 — FORWARD OOS AUTOMATIC COLLECTOR

This package intentionally separates the research collector from live strategy
logic.

Safety
------
- no orders
- no execution
- no paper-order mutation
- no quantity
- no B/E/CAP20/re-entry rule changes
- only writes the V62 forward research ledger

Important integration note
--------------------------
The collector requires BOTH:
1. midpoint audit events
2. every completed 1-minute underlying candle

To avoid guessing the current worker layout, first run the preflight inspection.

Commands
--------
cd ~/RB-ITOS-AI
source .venv/bin/activate
export PYTHONPATH=backend

python scripts/midpoint_v62_1_preflight.py

python -m pytest \
  tests/test_midpoint_v62_1_forward_oos_collector.py -v

Do NOT restart or patch the live worker yet.

Paste the preflight output. The adapter can then be wired to the exact current
worker without touching strategy decisions.

Stream adapter contract
-----------------------
The standalone runner expects JSONL records:

{"kind":"audit","event":{...midpoint audit event...}}

{"kind":"candle",
 "timestamp":"2026-09-29T10:06:00+05:30",
 "high":123.4,
 "low":120.1,
 "close":122.8}

Once wired, the sidecar writes completed forward cases into the existing V62
ledger.
