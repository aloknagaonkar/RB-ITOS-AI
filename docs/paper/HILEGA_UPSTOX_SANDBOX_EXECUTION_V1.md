# Hilega Upstox Sandbox Execution V1

This layer validates Hilega order flow against Upstox Sandbox. It is not live trading and is not wired into the live worker.

## Safety invariants

- Disabled by default: `HILEGA_UPSTOX_SANDBOX_ENABLED=0`.
- Kill switch active by default: `HILEGA_UPSTOX_SANDBOX_KILL_SWITCH=1`.
- Every invocation requires `--confirm SANDBOX_ONLY`.
- Orders are sent only to `https://api-sandbox.upstox.com`.
- Live trading tokens are neither read nor accepted.
- V1 permits exactly one dynamically resolved lot.
- `BULLISH ENTRY -> BUY CE`; `BEARISH ENTRY -> BUY PE`.
- Exit sells the exact contract and quantity recorded at entry.
- `event_id` provides idempotency; `trade_id` binds entry and exit.
- A non-terminal `REQUESTED` record is not automatically retried because the broker may have accepted it.

## Event contract

```json
{
  "event_id": "immutable-hilega-event-id",
  "trade_id": "immutable-hilega-trade-id",
  "event_type": "ENTRY",
  "direction": "BULLISH",
  "event_timestamp": "2026-10-06T09:30:00+05:30",
  "strategy_id": "HILEGA_DIRECTIONAL_SHADOW_V1"
}
```

## Deliberate rollout boundary

This phase is a manually invoked sandbox adapter. Automatic worker consumption, broker order-status reconciliation, fill accounting, session P&L limits and UI controls must be added and validated before unattended sandbox operation. Live execution remains out of scope.
