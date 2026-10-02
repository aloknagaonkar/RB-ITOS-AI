# ATM ±5 Trade Path Analysis V1

Research-only diagnostic. It does not change frozen strategy, paper, or live rules.

Run May 18 bullish confirmed signals:

```bash
python -m market_lab.atm_plus_minus_5_trade_path_analysis_v1 \
  --session-date 2026-05-18 \
  --direction BULLISH \
  --signal 10:45:23400 \
  --signal 12:20:23500 \
  --signal 13:30:23650 \
  --signal 14:40:23600 \
  --horizon-minutes 30 \
  --csv data/historical-evidence/atm-pm5-trade-path-2026-05-18-v1.csv \
  --json-output data/historical-evidence/atm-pm5-trade-path-2026-05-18-v1.json
```

For each signal it checks exact ATM-5 ... ATM+5 with:
- next-minute OPEN entry
- exact 1-minute OHLC only
- no interpolation / no nearest strike / no nearest timestamp
- MAE/MFE
- +1/+2/+5/+10/+15/+20/+30 minute returns
- -5/-7.5/-10 touches
- +5/+10/+20 touches
- post--5% recovery diagnostics
