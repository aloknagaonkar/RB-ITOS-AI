# Hilega Directional Coordinator v1 — isolated phase

This patch does not change the bullish or bearish strategy rules.

It introduces the agreed orchestration semantics:
- one ACTIVE owner only
- opposite ARMED may coexist as information
- opposite entry is suppressed while current owner is ACTIVE
- suppressed opposite entry is preserved as ARMED
- no same-candle reversal
- after exit, preserved opposite ARMED may continue on the next completed candle

The module is deliberately not wired into the live worker/API/UI yet.

Validation against the current source snapshot:
`29 passed`
across bullish strategy, bearish strategy, bearish historical replay, and coordinator tests.

Whipsaw mitigation is explicitly deferred.
