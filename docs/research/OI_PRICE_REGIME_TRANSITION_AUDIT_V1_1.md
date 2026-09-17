# OI_PRICE_REGIME_TRANSITION_AUDIT_V1_1

Research-only correction/expansion.

## Primary research basket
Uses moving ATM ±5 (11 strikes) by default.

All moving-basket deltas compare the **same physical current strikes** at T versus T-5/T-10/T-15.
No moving-basket-to-moving-basket PCR comparison is allowed.

## V1.1 corrections
1. Default research basket changed to ATM ±5.
2. PCR previous values use the exact same current physical strike basket at T-5/T-10/T-15.
3. Adds 5m/10m/15m CE delta, PE delta, imbalance and PCR-change horizons.
4. Adds futures 5m/10m/15m price trajectory.
5. Optional strategy replay JSON merges P1/WAIT_P2/P2/VWAP-rejection state into each candle.
6. Adds a human-readable interpretation string per candle.
7. Adds fixed-session PCR on the frozen 09:20 ATM ±5 basket:
   - `session_pcr_baseline_0920 = PE_fixed_09:20 / CE_fixed_09:20`
   - `session_pcr_current = PE_fixed_T / CE_fixed_T`
   - `session_pcr_change_0920_to_now = session_pcr_current - session_pcr_baseline_0920`

## PCR views

### Recent PCR — moving ATM ±5

At each candle T, the current ATM ±5 basket is selected once. PCR at T and the
comparison PCRs at T-5/T-10/T-15 all use those exact same physical strikes.

The audit preserves both the earlier ratio and its change:

- `pcr_current`
- `pcr_previous_same_strikes_5m`, `pcr_change_5m`
- `pcr_previous_same_strikes_10m`, `pcr_change_10m`
- `pcr_previous_same_strikes_15m`, `pcr_change_15m`

### Session PCR — fixed 09:20 ATM ±5

The 09:20 ATM ±5 basket is frozen for the whole session. Both baseline PCR and
current session PCR use those exact same morning strikes. This is deliberately
separate from moving-basket PCR and represents 09:20 → current-time context.

## Important semantics
- `LONG_BUILDUP`, `SHORT_BUILDUP`, `SHORT_COVERING`, `LONG_UNWINDING` use futures price + futures OI.
- Option-chain OI pressure remains separate.
- Fixed session context uses 09:20 ATM ±5 all day.
- Session PCR also uses that same fixed 09:20 ATM ±5 basket all day.
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
