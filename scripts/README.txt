Midpoint M2.5A — Forensics UX
================================

Adds the "better than Hilega" forensic layer that does not require exact option
provider wiring yet:

- latest details header at the top:
  session/trading date, latest evidence time, latest audit time/type,
  UI refresh time, source/mode, owner/direction, safety, stale-live warning
- lifecycle checkpoint comparison
- Explain this minute in historical replay
- factual "what must happen next" based on frozen lifecycle semantics

M2.5B remains the exact five-contract option-observation adapter:
ATM-2..ATM+2, correct CE/PE side, instrument, entry/latest/exit premium,
current/realized points and %, MFE/MAE, and as-of-minute historical progression.

No strategy-engine changes. No execution changes.

Run:
  cd ~/RB-ITOS-AI
  source .venv/bin/activate
  export PYTHONPATH=backend
  python scripts/apply_midpoint_m25a.py
  python scripts/verify_midpoint_m25a.py
