# Historical Replay UI/API V1

This slice exposes completed replay artifacts to the dashboard without changing
strategy logic or replay logic.

API:
- GET /api/live-shadow/replay/sessions
- GET /api/live-shadow/replay/status?date=YYYY-MM-DD
- GET /api/live-shadow/replay/checkpoints?date=YYYY-MM-DD
- GET /api/live-shadow/replay/events?date=YYYY-MM-DD
- GET /api/live-shadow/replay/health?date=YYYY-MM-DD
- GET /api/live-shadow/replay/step-audit?date=YYYY-MM-DD
- GET /api/live-shadow/replay/timeline?date=YYYY-MM-DD

The timeline endpoint combines checkpoint audit stages with observation lifecycle
events so the frontend does not have to rebuild that join itself.

Frontend:
- `frontend/src/historicalReplay.tsx`
- `frontend/src/historicalReplay.css`

The component shows date selection, analysis status, checkpoint count, observations,
open/closed state, audit-chain state, every 5m/10m/15m/ALL3 checkpoint, and an
expandable full audit with OI/PCR values and strategy lifecycle.

This package intentionally does NOT auto-patch App.tsx because the current dashboard
has evolved independently. The backend router patch is safe and automated. After
the API tests/build pass, inspect the current Live Shadow tab integration point and
mount `<HistoricalReplay />` beside it rather than guessing an App.tsx anchor.
