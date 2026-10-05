# Hilega Upstox Sandbox Live Worker V1

This worker submits only new, genuine Hilega directional events to Upstox Sandbox during one explicitly armed session.

## Mandatory boundaries

- Sandbox only; the live broker API and live trading token are never used.
- The session must be explicitly armed with `ARM_UPSTOX_SANDBOX_ONLY`.
- Arming records the current source-audit sequence as a historical fence.
- Only events after that sequence and on the exact armed date are eligible.
- One open trade maximum; entry and exit must share the same trade ID.
- Every dispatch is durable and idempotent across restarts.
- Any configuration, submission, overlap, unmatched-exit or order-limit failure engages the kill switch and disarms the worker.
- Upstox Sandbox acceptance validates API flow, not exchange fill or P&L.

## Required `.env` values

```text
UPSTOX_ACCESS_TOKEN=<analytics token>
UPSTOX_SANDBOX_ACCESS_TOKEN=<sandbox token>
HILEGA_UPSTOX_SANDBOX_ENABLED=1
HILEGA_UPSTOX_SANDBOX_KILL_SWITCH=0
HILEGA_UPSTOX_SANDBOX_LOTS=1
```

Do not configure `UPSTOX_TRADING_ACCESS_TOKEN` for this worker.

## Daily sequence

Before the session begins, arm that exact date. Then start the standalone worker. At the end of the session, disarm and stop it. Arming after a strategy signal deliberately fences out that earlier signal.
