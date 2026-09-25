Hilega Option Metadata Audit Patch

Purpose:
- Attach directional trade-dashboard metadata to the primary candle-by-candle audit.
- Show expiry, ATM, lifecycle status, entry boundary, and the exact missing option-data issue.
- Preserve exact option prices as unavailable when the causal minute is missing; no synthetic/fallback price is created.
- Frontend-only. No strategy/API/worker logic is changed.

Run from repo root:
  cd ~/RB-ITOS-AI
  source .venv/bin/activate
  python scripts/apply_option_metadata_audit_fix.py

Then:
  cd frontend
  npm run build

No API or worker restart is required.
