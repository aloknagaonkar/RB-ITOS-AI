Midpoint M2.4C — Live continuation projection
==============================================

Requires M2.4A + M2.4B.

Adds a LIVE ACTIVE continuation panel when the latest Midpoint entry has not
yet reached a structural terminal. It uses the same displayed lifecycle
semantics as historical replay: family, direction, BUY CE/PE intent,
entry/current NIFTY, directional move, futures/VWAP/raw diff, +20 proof,
classifier, and degraded state.

This is presentation-only and updates via the existing live polling.
It does not write synthetic CONTINUE events into immutable audit evidence.

Important: it does not fabricate a separate 1-minute live candle stream.
Historical replay remains the exact full minute-by-minute evidence view.

No strategy-engine or execution changes.

Run from ~/RB-ITOS-AI:
  source .venv/bin/activate
  export PYTHONPATH=backend
  python scripts/apply_midpoint_m24c.py
  python scripts/verify_midpoint_m24c.py
