Hilega P11 Operational UI package

Contains:
- backend/market_lab/hilega_directional_live_shadow_ui_v1.py
- tests/test_hilega_directional_live_shadow_ui_v1.py

Purpose:
Adds read-only operational visibility for session, expiry/source, option lifecycle,
restart restoration, cutoff, and market-evidence health while preserving observation-only safety.

Validation:
  export PYTHONPATH=backend
  python -m py_compile backend/market_lab/hilega_directional_live_shadow_ui_v1.py
  python -m pytest -q tests/test_hilega_directional_live_shadow_ui_v1.py
