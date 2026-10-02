Midpoint M2.5 layout polish v2
================================
Built against the current M2.5A source shape.

Changes:
- compact summary cards
- compact lifecycle cards
- ACTIVE TRADE immediately above live audit / historical replay
- EXIT DETAILS immediately below live audit / historical replay
- same arrangement in Live and Historical Replay

No backend, strategy, execution, or audit semantics changes.

Run:
  cd ~/RB-ITOS-AI
  source .venv/bin/activate
  export PYTHONPATH=backend
  python scripts/apply_midpoint_m25_layout_v2.py
  python scripts/verify_midpoint_m25_layout_v2.py
