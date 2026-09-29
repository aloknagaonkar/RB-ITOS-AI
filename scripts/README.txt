Midpoint M2.4B frontend bundle
================================

Requires M2.4A backend already applied and verified.

Adds:
- Hilega-style structured audit detail in LIVE and HISTORICAL REPLAY
- PASS/FAIL/INFO qualification tables
- Observed vs Required / what qualifies
- WHY / gap-to-qualify
- Futures VWAP ABOVE/BELOW
- CE/PE intent without fabricating exact strike
- Historical replay CONTINUE · BULLISH_ACTIVE / BEARISH_ACTIVE rows
- Source-aware historical banner:
  * V57 PARITY-PROVEN REPLAY
  * FORWARD OOS REPLAY · NO-REENTRY BASELINE
- Raw immutable audit remains available under collapsible details

Does not change strategy semantics or execution settings.

Run from ~/RB-ITOS-AI:
  source .venv/bin/activate
  export PYTHONPATH=backend
  python scripts/apply_midpoint_m24b.py
  python scripts/verify_midpoint_m24b.py

Do not restart services yet.
