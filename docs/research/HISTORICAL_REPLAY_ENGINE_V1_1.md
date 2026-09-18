# Historical Replay Engine V1.1 — Event-Driven Runtime

V1 proved the causal pipeline works, but a full historical day was too slow because
the live polling method was called once for every simulated minute, including long
periods when there was no option entry or open position.

V1.1 changes only the historical replay scheduler.

It does NOT change:
- `LiveShadowProductionCoordinatorV1`
- normalized OI/PCR logic
- ALL3 logic
- C2 logic
- futures alignment mapping
- exact ATM option resolution
- `LiveShadowRuntimeAdapterV1`
- `ShadowEngine`
- stop / BE / trail / time-exit policy

Instead of polling every historical minute, V1.1 invokes the unchanged production
runtime only when that runtime can make progress:
- exact next-minute entry becomes evaluable
- an exact option 1m bar has completed
- missing exact entry becomes eligible to fail closed

Five-minute checkpoints are still processed sequentially from 09:20 through 15:25.

The CLI now prints checkpoint and runtime progress so a replay never appears frozen.

## Run

Stop any old V1 replay process first.

Then:

`python -m market_lab.historical_replay_day_v1_1 --date 2026-09-18 --overwrite`

## Validation

Compare V1.1 against the earlier V1 partial baseline for timestamps that V1 completed.
The same observation IDs, C2 decisions, futures decisions, exact option selection,
entry price, and exit result should match.

Only after behavioral parity is confirmed should V1.1 replace the replay path used by UI.
