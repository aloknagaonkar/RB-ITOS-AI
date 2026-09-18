# Historical Replay Data Readiness V1

First slice of the one-day Historical Replay capability.

Provides:
- readiness check for any selected historical date
- production option-chain snapshot count/span
- isolated replay cache
- missing NIFTY futures download
- exact option 1-minute download by instrument, on demand
- no nearest-strike fallback, synthesis, or interpolation
- no writes to live-shadow production event/audit files
- execution and paper orders remain disabled

Cache:
`data/live-observation/replay-cache/YYYY-MM-DD/`

CLI:
`python -m market_lab.historical_replay_data_v1 --date 2026-09-18 check`

`python -m market_lab.historical_replay_data_v1 --date 2026-09-18 download-missing`

API:
- GET `/api/live-shadow/replay-data/readiness?session_date=YYYY-MM-DD`
- POST `/api/live-shadow/replay-data/download-missing?session_date=YYYY-MM-DD`
- POST `/api/live-shadow/replay-data/download-option`

Exact option data intentionally remains ON_DEMAND until the causal replay selects the exact
CE/PE instrument. The next slice is the one-day causal replay runner emitting the same
step-audit schema used by Live Shadow.
