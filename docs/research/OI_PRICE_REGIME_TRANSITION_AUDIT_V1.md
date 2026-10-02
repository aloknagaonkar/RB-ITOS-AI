# OI_PRICE_REGIME_TRANSITION_AUDIT_V1

Generic date-driven, research-only 5-minute regime audit. It does not change Strategy #2, paper rules, or live trading.

It records moving ATM±2 option OI, exact same-strike 5m OI deltas, PCR change, fixed 09:20 ATM±2 session buildup, completed futures 5m price/VWAP, futures OI status, persistence streaks, and optional retrospective labels.

Futures OI status semantics:
- LONG_BUILDUP = futures price up + futures OI up
- SHORT_BUILDUP = futures price down + futures OI up
- SHORT_COVERING = futures price up + futures OI down
- LONG_UNWINDING = futures price down + futures OI down

Keep this separate from option-chain OI imbalance. Raw option OI alone cannot identify buyer-vs-writer initiation.

Any date:
```bash
python -m market_lab.oi_price_regime_transition_audit_v1 \
  --session-date 2026-05-18 \
  --csv data/historical-evidence/oi-price-regime-audit-2026-05-18-v1.csv \
  --json-output data/historical-evidence/oi-price-regime-audit-2026-05-18-v1.json
```

Aug 25 with evaluation-only chart labels:
```bash
python -m market_lab.oi_price_regime_transition_audit_v1 \
  --session-date 2026-08-25 \
  --label 09:15-09:30:BULLISH \
  --label 09:35-10:20:BEARISH \
  --label 10:25-11:55:BULLISH \
  --label 12:00-13:10:BEARISH \
  --label 13:25-15:30:BULLISH \
  --csv data/historical-evidence/oi-price-regime-audit-2026-08-25-v1.csv \
  --json-output data/historical-evidence/oi-price-regime-audit-2026-08-25-v1.json
```

The labels never feed causal feature calculation. If the futures CSV has no OI column, futures OI status remains UNAVAILABLE while the rest of the audit still runs.
