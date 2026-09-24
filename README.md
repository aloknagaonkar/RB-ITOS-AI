# Phase 6.3A — Current-Day Directional Timeline Recovery

This patch adds a backend-only recovery path for a session whose historical
broker candles are unavailable but whose live Hilega audit already contains
completed `UNDERLYING_5M_BUILD` bars.

It does not synthesize candles and does not recalculate from partial directional
audit records. It replays the already-recorded 5m OHLC through the same
`HilegaDirectionalCoordinatorV1`, after warming indicators from existing cache.

Primary use now:

```bash
PYTHONPATH=backend python -m market_lab.hilega_current_day_directional_recovery_cli_v1 \
  --date 2026-09-24
```

The output goes to the standard historical directional replay location, so the
existing Historical Replay UI can consume it without a UI redesign.

This is the recovery core. Automatic live-worker bootstrap wiring should be
enabled only after the Sep 24 recovery output is validated against the captured
live candle evidence.
