# P3H.2 Date-Driven Historical Replay V1

This phase removes the temporary `--config-id` and `--futures-json` requirements.

The confirmed futures source is:

`data/historical-evidence/midpoint-v2-nifty-futures-vwap-v1-development.csv`

Its rows are 1-minute NIFTY futures OHLCV. The adapter aggregates exactly five
constituent 1-minute rows into one causal 5-minute candle and then uses the same
`completed_futures_vwap()` function as the live runtime.

The historical OI side is reconstructed from `historical-positioning-cache*`:

- fixed 09:20 ATM±2 = session context
- moving current ATM±2 = short-term OI context
- current vs T-5 uses the same physical current five strikes
- session context uses the same physical 09:20 five strikes
- 5m imbalance = PE 5m delta - CE 5m delta
- session imbalance = PE session delta - CE session delta

Strategy evaluation starts at 09:25, after the genuine 09:20 baseline exists.

## Single session

```bash
python -m market_lab.paper_historical_replay_cli_v1 \
  --session-date 2026-08-25
```

## Date range

```bash
python -m market_lab.paper_historical_replay_cli_v1 \
  --from-date 2026-08-01 \
  --to-date 2026-09-08
```

Only dates available in BOTH positioning cache and futures CSV are replayed.

This remains a state-machine validation replay. It does not yet simulate the
option entry/exit portfolio. That comes in P3A/P3H.3.

Important governance: do not use an untouched validation session to tune rules
after viewing its replay results.
