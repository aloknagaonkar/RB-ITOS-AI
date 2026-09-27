B FAMILY — TRAILING-SL 180-SESSION CHARACTERIZATION V15
===========================================================

Prerequisite
------------
V14.1 data-health audit must PASS:
- 180/180 framework, underlying and futures/VWAP sessions
- 0 duplicate conflicts
- canonical B parity 45 = 27 older + 18 latest60

Purpose
-------
Compare whether causal structural trailing can preserve B's large runners
better than the current V8.2 breakeven-after-+20 behavior.

Models
------
STRUCTURAL
HYBRID_MIN15_ATR1_BE20   (imported unchanged from V8.2)
TRAIL_T1_SWING1
TRAIL_T2_SWING2

T1:
- initial risk min(15, causal ATR14)
- +20 proof
- confirmed 1m pivot with 1 left / 1 right bar
- new trail applies next bar
- never widens
- no forced breakeven

T2:
- same
- 2 left / 2 right bars (slower)
- next-bar only
- never widens
- no forced breakeven

Run
---
cd ~/RB-ITOS-AI
source .venv/bin/activate
export PYTHONPATH=backend

python scripts/b_family_trailing_sl_180_v15.py \
  | tee /tmp/b-family-trailing-sl-180-v15.txt

Paste the full output back.

Interpretation
--------------
This is characterization on the same historical 180-session research universe.
It is NOT independent validation and cannot by itself freeze a production exit.
