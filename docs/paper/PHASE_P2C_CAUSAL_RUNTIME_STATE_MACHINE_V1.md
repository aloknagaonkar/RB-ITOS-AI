# Phase P2C — Causal Runtime State Machine V1

This phase connects the already-tested live OI feature engine, futures VWAP feed, production guards,
and persistent paper signal journal.

## Runtime lifecycle

1. Read newest live observation.
2. Validate active option expiry.
3. Build causal 5m OI feature.
4. Detect a fresh P1 only when:
   - bullish: previous imbalance <= 0, current > 0, PCR 5m change > 0,
     session imbalance improving
   - bearish: previous imbalance >= 0, current < 0, PCR 5m change < 0,
     session imbalance weakening
5. Fetch latest completed NIFTY futures VWAP.
6. Validate futures health.
7. Require VWAP side alignment:
   - bullish -> ABOVE
   - bearish -> BELOW
8. Persist WAIT_P2.
9. On next checkpoint:
   - same direction persists -> P2_CONFIRMED
   - otherwise -> P2_PERSISTENCE_FAILED
10. Opposite P1 does NOT auto-reverse.

## Safety

This phase does NOT open a paper position.
`paper_entry_allowed=true` is only an internal handoff flag after P2 confirmation.
P3 must still perform:
- exact ATM resolution at P2 time
- exact CE/PE quote lookup
- quote freshness
- ASK-side simulated entry
- capacity check
- persistent paper position creation

Live broker execution remains absent.

## Service

Manual runtime validation:

```bash
python -m market_lab.oi_vwap_causal_service_v1
```

This service is browser independent.

Do not daemonize it yet. First inspect runtime health and event output.
