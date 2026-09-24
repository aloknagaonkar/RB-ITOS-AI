# Historical Option Sidecar Active-Expiry Fix v1

This is an acquisition-layer fix only.

Behavior:
- If `expiry < provider_as_of`, use the existing expired-instruments contract/candle endpoints.
- If `expiry >= provider_as_of`, use the existing active-option contract and active historical candle endpoints.
- A zero-contract catalog is `UNAVAILABLE`, not `AVAILABLE`.
- A zero-row option result is `UNAVAILABLE`, not `AVAILABLE`.
- No nearest date, strike, minute, or alternate contract fallback is introduced.

The Sep-23 / Sep-29 case is the motivating example: on 2026-09-24 the
2026-09-29 expiry is still active, so it must be acquired from active endpoints.

Validation against the current source snapshot:
`43 passed`

No API/worker restart is required.

Important after install:
The existing Sep-23 cache was created by the old code with `AVAILABLE` + zero rows.
Delete only that stale cache file (or use `--refresh`) before rebuilding Sep-23.
