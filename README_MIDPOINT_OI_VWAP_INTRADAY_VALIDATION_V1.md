# MIDPOINT_OI_VWAP_INTRADAY_VALIDATION_V1

Today-only research adapter for current-session Upstox intraday data.

## Scope

- Pulls NIFTY spot 1-minute candles from the current intraday endpoint.
- Pulls current NIFTY futures 1-minute candles and computes prospective cumulative session VWAP.
- Pulls the current expiry option chain and all exact moving-ATM CE/PE contracts required by the observed spot path.
- Reconstructs synchronized 5-minute option price/OI states.
- Emits Arm A transition signals.
- Reconstructs first RED/GREEN opening-midpoint structures and applies T+3 thresholds loaded from the existing frozen V3.2 state artifact.
- Emits Arm C only when midpoint T+3 direction aligns with the latest completed 5-minute OI/VWAP checkpoint.
- Uses exact ATM at signal timestamp and next-minute OPEN.
- Applies 0.5 percentage-point round-trip cost to passive 1/3/5/10/15 minute returns.
- Research only. Never emits paper/live orders.

## Important limitation

The Arm C path is explicitly `INTRADAY_DIAGNOSTIC_ONLY`. It is intended to answer "did today's clear move line up with our frozen midpoint + OI/VWAP concept?" It does not replace the canonical historical structural-reconstruction pipeline and must not be used as promotion evidence without parity checking.

## Run

```bash
cd ~/RB-ITOS-AI
source .venv/bin/activate
set -a
source .env
set +a

python -m pytest tests/test_midpoint_oi_vwap_intraday_validation_v1.py -v

python -m market_lab.midpoint_oi_vwap_intraday_validation_v1 \
  --session-date 2026-09-15 \
  --expiry 2026-09-15 \
  --output-dir data/historical-evidence/intraday-validation
```

Then:

```bash
jq '{
  research_version,
  research_status,
  coverage,
  positioning_config,
  comparison,
  arm_a: .arm_a.summary,
  arm_c: .arm_c.summary,
  midpoint_diagnostics,
  issues
}' \
data/historical-evidence/intraday-validation/midpoint-oi-vwap-intraday-validation-2026-09-15.json
```
