# Runtime Adapter V1 - Production Wiring Checklist

## Existing-source discovery
- [ ] Locate the exact function that emits live 5m/10m/15m ALL_3.
- [ ] Confirm it uses completed candles only.
- [ ] Locate most recent prior directional ALL_3.
- [ ] Locate exact C1 and C2 spot values.
- [ ] Locate existing futures OI state producer.
- [ ] Confirm its output enum values.
- [ ] Locate exact moving ATM resolver.
- [ ] Locate exact CE/PE instrument-key resolver.
- [ ] Locate exact next-minute option OPEN source.
- [ ] Locate completed 1-minute option OHLC source.

## Adapter wiring
- [ ] Call `on_new_all3()` only after completed 5m ALL_3 calculation.
- [ ] Schedule/route the exact next completed 5m checkpoint to `on_candle2()`.
- [ ] Call `on_exact_option_resolved()` only after C2 + futures pass.
- [ ] Call `on_exact_next_minute_open()` at the exact minute.
- [ ] Route completed option 1m candles into `on_option_minute()` while open.
- [ ] Stop routing option candles once state becomes CLOSED/REJECTED/INCOMPLETE.

## Safety
- [ ] No broker client imported.
- [ ] No place-order method reachable.
- [ ] No nearest-strike fallback.
- [ ] No nearest-time fallback.
- [ ] Missing exact dependency => INCOMPLETE.
- [ ] Futures disagreement => REJECTED.
- [ ] ALL_3 C2 failure => REJECTED.
- [ ] Duplicate detection survives process restart.

## Audit
- [ ] Every live observation has deterministic observation ID.
- [ ] Every state change creates an immutable audit event.
- [ ] Hash-chain verification passes.
- [ ] Ledger can be regenerated from events.jsonl.
- [ ] Daily counts reconcile.
- [ ] Every CLOSED trade has entry/exit/P&L.
- [ ] Every rejected/incomplete observation has a reason.

## Go-live shadow acceptance
- [ ] Integration replay passes.
- [ ] One controlled live session completed.
- [ ] First session manually reconciled against raw market/runtime output.
- [ ] No execution/paper orders generated.
