Midpoint M2.4A backend bundle
=============================

Purpose
-------
Adds UI-only audit enrichment and historical replay continuation projection:
- PASS/FAIL checks
- observed vs required
- gap-to-qualify
- futures/VWAP interpretation
- CE/PE intent (no fabricated contract)
- presentation-only CONTINUE state for historical replay

It does NOT change Candidate A, Family B/E ownership, +20, classifier,
DEGRADED, CAP20, no-reentry baseline, execution, paper orders, or quantity.

Usage on the VM
---------------
1) unzip midpoint_m24a_backend_bundle.zip
2) from ~/RB-ITOS-AI:

   source .venv/bin/activate
   export PYTHONPATH=backend

   python /path/to/apply_midpoint_m24a.py
   python /path/to/verify_midpoint_m24a.py

Do not restart services yet.

Expected safety
---------------
observation_only = true
execution_enabled = false
paper_order_enabled = false
quantity = None

The patch script creates:
backend/market_lab/midpoint_strategy/live_shadow_ui.py.pre-m2-4a.bak
