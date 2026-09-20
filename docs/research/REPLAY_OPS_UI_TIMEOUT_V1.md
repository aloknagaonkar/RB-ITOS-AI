# Replay Operations UI Timeout V1

Observed behavior on 2026-09-17:
- direct `POST /api/live-shadow/replay-ops/run` returned HTTP 200 in ~13.99s;
- the backend returned a QUEUED job and the worker subsequently ran normally;
- the frontend generic request helper defaults to 20 seconds;
- the run/download action used that generic default without an override.

The replay backend is already asynchronous. The POST route performs a
synchronous readiness check before launching the background worker, so launch
latency can approach or exceed the generic 20-second browser timeout.

This patch changes only the launch request in
`frontend/src/historicalReplayOperations.tsx`:
- replay/download launch timeout: 60 seconds;
- readiness requests: unchanged at 20 seconds;
- job polling: unchanged at 20 seconds;
- backend execution semantics: unchanged;
- paper/live execution remains disabled.

This is a UI resilience change, not a strategy or replay-engine change.
