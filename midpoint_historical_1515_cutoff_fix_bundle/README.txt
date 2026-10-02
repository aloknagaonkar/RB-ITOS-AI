MIDPOINT HISTORICAL 15:15 CUTOFF FIX
=====================================

Folder placement:

RB-ITOS-AI/
├── midpoint_historical_1515_cutoff_fix_bundle/
│   ├── install.py
│   └── files/
├── scripts/
└── tests/

Install:

  cd ~/RB-ITOS-AI
  source .venv/bin/activate
  python midpoint_historical_1515_cutoff_fix_bundle/install.py

The fix preserves the exact 360 replay minutes from 09:15 through 15:14.
Audit bookkeeping at 15:15 or later remains in the immutable live audit but is
not required to match a replay candle that deliberately does not exist.

No API, market worker, live-shadow worker, or publisher is restarted.
The already-running publisher will use the corrected child materializer on its
next polling attempt.

