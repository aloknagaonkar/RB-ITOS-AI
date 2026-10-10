# Tested V2 loss validation

Separate offline full-lifecycle replay. Nothing is installed or enabled. Midpoint remains excluded. No orders, broker requests, service changes or writes to live/frozen evidence are made. Requires the installed `market_lab.hilega_v2_alignment_replay_v1` engine.

## Five independent runs

| Policy | Additional rule | Other entry/exit rules |
|---|---|---|
| BASELINE | None | Original tested V2 |
| BULL_GAP_GE5 | Bullish directional gap must be >=5 at entry | Unchanged; pending setup may wait for gap to reach 5 within its existing window |
| BULL_NO_13_TO14 | Block bullish entry decisions from 13:00 inclusive to 14:00 exclusive IST | Bearish entries and existing position exits unchanged |
| RECHECK_ALIGNMENT | At entry evaluation require both latest completed 5m and current provisional ordering: bullish RSI9>EMA3>WMA21; bearish reverse | Cancel pending setup if either ordering is invalid; original strength/persistence/gap gates remain mandatory |
| CLOSE_PROFIT_PROTECTION | After a completed 1m close reaches >=+20 Nifty points, track best closed-minute profit. Exit at a later completed-minute close if profit falls to <=50% of that peak | Original dual exit and cutoff remain; whichever fires first closes the trade |

20 points and 50% are an explicit first experimental protection rule, not optimized parameters or proven best levels. Profit checks use closes available at that moment, not future maximum favourable excursions or intrabar extremes. The alignment test is deliberately stronger than merely keeping the original setup alive; it includes provisional ordering.

Every variant replays the whole position lifecycle. Earlier exits and rejected/delayed entries can create different subsequent trades. Do not interpret CSV membership changes as simple deletions from the baseline.

## Run on VM

Extract this folder into RB-ITOS-AI, beside backend and scripts. No installer or restart required.

```bash
cd ~/RB-ITOS-AI
PYTHONPATH=backend:. .venv/bin/python hilega_v2_loss_validation/run.py --self-test
PYTHONPATH=backend:. .venv/bin/python hilega_v2_loss_validation/run.py \
  --end-date 2026-10-09 \
  --output-root data/historical-evidence/hilega-v2-loss-validation-v1
```

Default evaluation is July 10–October 9, with separate one-month and three-month summaries by direction. Prior cached dates warm up indicators. The same dates must succeed for ALL five variants before entering the comparison. A source compatibility check stops if expected research engine code differs. Existing output folders are preserved: select a new output path for a repeat run.

For four days only:

```bash
PYTHONPATH=backend:. .venv/bin/python hilega_v2_loss_validation/run.py \
  --start-date 2026-10-06 --end-date 2026-10-09 \
  --output-root data/historical-evidence/hilega-v2-loss-oct6-9-v1
```

Use repeated `--cache-root PATH` if needed. Default cache roots match the installed V2 replay engine; later roots take precedence. Missing/empty cache dates are reported, not assumed to be holidays. A custom start shorter than a requested window is explicitly `window_truncated=true` in the summary.

## Outputs

- summary.csv: gains/losses, net, gain/loss ratio, closed-trade drawdown, directions and windows.
- daily.csv: date-wise result for each policy.
- trades.csv / losses.csv: signal, entry/exit time and prices, points, strength, gap, expansion and exit evidence.
- attribution.csv: matched entries, baseline-only entries and variant-only entries; their net effects reconcile to the result change. IDs can shift across variants, so matching uses direction, entry time and entry price.
- sessions/DATE/POLICY.json: full candle audit, waiting/rejection checks, exit evidence and setup records.
- coverage.csv / report.json: input coverage, baseline rules and source hashes.

## Completed local one-month replay

September 10–October 9: 20 evaluated sessions. All 104 baseline trades exactly match the supplied VM CSV in direction, entry/exit times, prices, points and exit reason. This confirms the comparison baseline for this window, not live/chart parity.

| Policy | Trades | Gains | Losses | Net | Gain/loss | Drawdown | Change |
|---|---:|---:|---:|---:|---:|---:|---:|
| Baseline | 104 | 2050.20 | 1231.45 | 818.75 | 1.665 | 344.40 | 0 |
| Bullish gap >=5 | 104 | 2040.60 | 1246.80 | 793.80 | 1.637 | 347.90 | -24.95 |
| No bullish 13:00–14:00 | 100 | 2012.70 | 1104.05 | 908.65 | 1.823 | 289.80 | +89.90 |
| Recheck both alignments | 96 | 1839.85 | 1200.15 | 639.70 | 1.533 | 383.00 | -179.05 |
| Close-based profit protection | 130 | 1966.70 | 1361.75 | 604.95 | 1.444 | 423.20 | -213.80 |

The time filter is the only improving candidate here. Profit protection created 29 variant-only entry events, illustrating why faster exits can produce additional losses. Gap >=5 delayed/replaced four entries rather than simply deleting weak-gap losing trades. Do not activate any variant yet: these candidates were selected after examining historical outcomes. The one-month period is not an independent holdout, and three-month full replay must still run on the VM.

`local_last_month` contains the one-month replay; its three-month rows are marked truncated, not full three-month results. `local_oct6_9` contains the four-day replay. July/early-August raw inputs were unavailable locally, so the 334-trade supplied CSV was used for diagnostics, not fabricated into a full replay.

These are reconstructed Nifty points before fees, slippage and option fills. No live strategy, Sandbox gate, expiry selection, quantity or UI is changed.
