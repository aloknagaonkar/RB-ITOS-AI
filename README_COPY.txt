Branch C V1.4 — Same-candle EMA3-WMA21 gap audit

Purpose:
- Check whether same-candle EMA3-WMA21 gap expansion removes 2026-09-15 11:10.
- Verify whether accepted 2026-09-21 signals still pass.
- No next-candle confirmation, so added delay is always 0 minutes.

Requires prior V1.1 and V1.3 scripts already in repo.

Run:
python -m pytest tests/test_validate_hilega_milega_bullish_gap_audit_v1_4.py -v

python scripts/validate_hilega_milega_bullish_gap_audit_v1_4.py \
  --session-date 2026-09-15 \
  --session-date 2026-09-21 \
  --intraday-date 2026-09-21

Paste:
=== BRANCH C SAME-CANDLE GAP AUDIT ===
