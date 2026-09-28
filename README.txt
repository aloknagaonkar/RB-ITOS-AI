MIDPOINT V62 — RE-ENTRY OOS FREEZE + FORWARD VALIDATION

Why this phase exists
---------------------
V61 used all 9 observed re-entry cases to screen second-leg management.
Therefore those same 9 cases are development data and must NOT be called OOS.

V62 freezes exactly two research candidates before collecting new events:

R1
  Existing frozen post-CAP20 re-entry trigger.
  Once second-leg favorable excursion reaches +20, protect +10 on the first
  completed 1m close back to <= +10.

R2
  Existing frozen post-CAP20 re-entry trigger.
  Once running second-leg favorable excursion reaches +20, exit on the first
  completed 1m close <= running MFE - 20.

Validated baseline remains:
  CAP20 rescue -> final exit -> NO RE-ENTRY.

Promotion gate:
  minimum 20 NEW comparable re-entry events
  preferred 30+

Initial setup:
  cd ~/RB-ITOS-AI
  source .venv/bin/activate
  export PYTHONPATH=backend

  python scripts/midpoint_v62_reentry_oos_forward_validation.py

This creates an empty forward ledger and verifies the freeze.

Important:
- Do not backfill the 9 V61 cases into the V62 ledger.
- Do not change R1/R2 thresholds after the freeze.
- No live strategy mutation is required.
- No restart is required.
