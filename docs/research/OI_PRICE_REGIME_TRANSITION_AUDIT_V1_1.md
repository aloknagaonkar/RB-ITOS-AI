# OI_PRICE_REGIME_TRANSITION_AUDIT_V1_1

Research-only correction/expansion.

## Primary research basket
Uses moving ATM ±5 (11 strikes) by default.

All moving-basket deltas compare the **same physical current strikes** at T versus T-5/T-10/T-15.
No moving-basket-to-moving-basket PCR comparison is allowed.

## V1.1 corrections
1. Default research basket changed to ATM ±5.
2. PCR previous value uses the exact same current physical strike basket at T-5.
3. Adds 5m/10m/15m CE delta, PE delta, imbalance and PCR-change horizons.
4. Adds futures 5m/10m/15m price trajectory.
5. Optional strategy replay JSON merges P1/WAIT_P2/P2/VWAP-rejection state into each candle.
6. Adds a human-readable interpretation string per candle.

## Important semantics
- `LONG_BUILDUP`, `SHORT_BUILDUP`, `SHORT_COVERING`, `LONG_UNWINDING` use futures price + futures OI.
- Option-chain OI pressure remains separate.
- Fixed session context uses 09:20 ATM ±5 all day.
- Exact same timestamp/strike/side option-OHLC OI fallback only; no interpolation or nearest-strike fallback.
- Retrospective labels are evaluation-only.

## Recommended Aug 25 run

First save the existing strategy replay:

```bash
python -m market_lab.paper_historical_replay_cli_v1 \
  --session-date 2026-08-25 \
  --events all \
  > data/historical-evidence/paper-replay-events-2026-08-25.json
```

Then run V1.1:

```bash
python -m market_lab.oi_price_regime_transition_audit_v1_1 \
  --session-date 2026-08-25 \
  --moving-wings 5 \
  --strategy-events-json data/historical-evidence/paper-replay-events-2026-08-25.json \
  --label 09:15-09:30:BULLISH \
  --label 09:35-10:20:BEARISH \
  --label 10:25-11:55:BULLISH \
  --label 12:00-13:10:BEARISH \
  --label 13:25-15:30:BULLISH \
  --csv data/historical-evidence/oi-price-regime-audit-2026-08-25-v1-1.csv \
  --json-output data/historical-evidence/oi-price-regime-audit-2026-08-25-v1-1.json
```

The same command works for any date with available historical positioning/futures data.
