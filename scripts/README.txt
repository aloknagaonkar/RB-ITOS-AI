Midpoint M2.5 layout polish
=============================

Changes:
- compact Owner/Direction/Family State/Latest Event/Boundary/Safety cards
- compact Entry/+20/Classifier/Degraded/CAP20/Structural Terminal cards
- ACTIVE TRADE section immediately above the candle-by-candle audit/replay
- EXIT DETAILS section immediately below the candle-by-candle audit/replay
- same layout behavior for LIVE and HISTORICAL REPLAY

No backend or strategy changes.

Run:
  cd ~/RB-ITOS-AI
  source .venv/bin/activate
  export PYTHONPATH=backend
  python scripts/apply_midpoint_m25_layout.py
  python scripts/verify_midpoint_m25_layout.py
