# Hilega bootstrap reconstructed-entry projection patch

Fixes a restart boundary where the append-only journal may contain:
- a pre-restart ARMED candle,
- an option lifecycle restore/retry proving `signal_bar` + entry `source`,
- later `BULLISH_ACTIVE` candles,
but no canonical strategy-decision record for the signal bar itself.

The patch adds a read-only, explicitly marked `RECONSTRUCTED_ENTRY` projection.
It does not modify or backfill `step-audit.jsonl`, and it does not fabricate
indicator or OHLC values.

Files changed by installer:
- backend/market_lab/hilega_milega_audit_report_v1.py
- frontend/src/hilegaDecisionTable.tsx

Added test payload:
- files/tests/test_hilega_bootstrap_reconstructed_entry_projection_v1.py
