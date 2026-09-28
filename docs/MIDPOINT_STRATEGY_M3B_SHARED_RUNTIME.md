# Midpoint Strategy — M3B Shared Runtime

M3B connects Family B to the existing shared live-shadow process without creating
a separate worker architecture.

## Runtime path

```text
UpstoxLiveShadowSourcesV1
  ├─ NIFTY underlying 1m
  └─ NIFTY front-future 1m
          ↓
MidpointLiveShadowCoordinatorV1
          ↓
M2 AuditableFamilyBEngine
          ↓
data/live-observation/midpoint-strategy-v1/audit.jsonl
          ↓
M3 API/UI workspace
```

The worker integration is optional and inert by default:

```text
MIDPOINT_SHADOW_ENABLED=0
```

When eventually enabled, the same Hilega/Hilega-Directional worker process calls
the Midpoint coordinator after its existing coordinator. No new worker process is
created.

## Implemented Family B flow

- ignore 09:15–09:19
- first later RED/GREEN completed 5m references
- exact 1m midpoint CLOSE break
- exact 1m original boundary CLOSE break
- B_DELAYED_FULL_CANDIDATE_A within 10 minutes
- raw front-future close versus cumulative session close-volume VWAP
- exact minute alignment, no interpolation/nearest substitution
- +20 proof
- exact +10m runner classification
- DEGRADED state
- recovery
- CAP20 rescue through M2 engine
- one post-rescue re-entry through M2 engine
- original full-range structural terminal
- no same-candle reversal
- one active Family-B direction at a time

## Safety

```text
observation_only=true
execution_enabled=false
paper_order_enabled=false
quantity=None
```

No option shadow and no orders are added in M3B.
