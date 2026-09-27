B FAMILY — FIVE-SESSION POST-08-SEP UNSEEN BATCH VALIDATION V11
================================================================

Sessions:
- 2026-09-10
- 2026-09-11
- 2026-09-15
- 2026-09-17
- 2026-09-18

Inputs are the repository's existing 1-minute underlying and futures caches.

V11 imports the repo's frozen prospective session-VWAP implementation:
market_lab.midpoint_v2_nifty_futures_vwap_v1.add_session_vwap()

That implementation uses cumulative:
  ((high + low + close) / 3) * volume
divided by cumulative volume.

It also imports:
- frozen midpoint structural functions
- frozen Family-B detector and measurement
- unchanged V8.2 risk functions

15 Sep is retained even though V10.1 found NO_B_EVENT.

Run:
cd ~/RB-ITOS-AI
source .venv/bin/activate
export PYTHONPATH=backend

python scripts/b_family_unseen_batch_validation_v11.py \
  | tee /tmp/b-family-unseen-batch-v11.txt

Paste the full output back.

Research only. No strategy/runtime/execution changes.
