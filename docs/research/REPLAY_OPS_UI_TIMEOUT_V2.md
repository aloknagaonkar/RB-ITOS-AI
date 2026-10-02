# Replay Operations UI Timeout V2

This patch updates the frontend replay-operations page so that both long-running
request types use a 60-second client timeout:

- `GET /api/live-shadow/replay-ops/readiness`
- `POST /api/live-shadow/replay-ops/run`
- `POST /api/live-shadow/replay-ops/download-missing`

The generic `requestJson()` default remains 20 seconds, so normal job polling and
other lightweight requests are unchanged.

Reason:
The backend readiness calculation can legitimately take around 14-20+ seconds
for a replay date, which can exceed the frontend's generic 20-second
`AbortController` timeout even though the backend is healthy.

This is a UI timeout/resilience change only.
No strategy logic, replay logic, execution flags, or paper-order behavior changes.
