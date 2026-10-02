# Historical Replay Engine V1

This is the one-day causal replay engine for the current Live Shadow strategy.

It intentionally reuses `LiveShadowProductionCoordinatorV1`, so these remain the
same between Live Shadow and Historical Replay:

- snapshot selection
- normalized 5m/10m/15m features
- ALL3 decision
- candidate detection
- C2
- futures confirmation
- exact ATM option resolution
- next-minute entry
- option minute health
- option lifecycle / exit state machine

## Historical data sources

The coordinator only needs two market-source methods:

- `futures_oi_at_checkpoint(checkpoint)`
- `option_intraday_1m(instrument_key)`

Historical Replay implements exactly those interfaces.

Futures are reconstructed causally from two strict, completed 5-minute windows
of cached 1-minute NIFTY futures candles.

Exact option candles are loaded from cache or downloaded for the exact selected
instrument only. No nearest strike, interpolation, or synthetic fallback exists.

## Replay clock

The replay advances from 09:20 IST through 15:31 IST one minute at a time.
Five-minute checkpoints are processed at 09:20, 09:25, ..., 15:25.

The per-minute clock is necessary to reproduce exact next-minute option entry
and completed one-minute option-bar processing.

## Output isolation

`data/live-observation/replay/YYYY-MM-DD/`

- `events.jsonl`
- `health.jsonl`
- `step-audit.jsonl`
- `checkpoints.json`
- `replay-status.json`

No production shadow file is written.

## Run

First ensure readiness:

`python -m market_lab.historical_replay_data_v1 --date 2026-09-18 check`

Then:

`python -m market_lab.historical_replay_day_v1 --date 2026-09-18`

If intentionally re-running:

`python -m market_lab.historical_replay_day_v1 --date 2026-09-18 --overwrite`

## Validation

After replay:

`cat data/live-observation/replay/2026-09-18/replay-status.json`

`tail -30 data/live-observation/replay/2026-09-18/step-audit.jsonl`

The next phase is API/UI wiring so this date-scoped replay uses the same
visual dashboard as Live Shadow.
