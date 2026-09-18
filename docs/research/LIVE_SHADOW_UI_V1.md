# LIVE_SHADOW_UI_V1

Adds a dedicated **Live shadow** workspace to the existing React/Vite research UI.

## Backend API

- `GET /api/live-shadow/status`
- `GET /api/live-shadow/observations`
- `GET /api/live-shadow/trades`
- `GET /api/live-shadow/health`
- `GET /api/live-shadow/daily-summary?session_date=YYYY-MM-DD`
- `GET /api/live-shadow/observation/{observation_id}`

The API reads the append-only audit and health files. It does not write strategy state and has no order endpoint.

## UI

The new workspace displays:

- observation-only safety banner;
- total/rejected/incomplete/open/closed counts;
- aggregate recorded net-return percentage points;
- latest data-health state;
- audit hash-chain state;
- live observations table;
- direction, stage, ALL3, futures, SPOT_LAG, contract, entry, stop and P&L;
- per-observation timeline with every audit event;
- recent data-health records.

The page polls every 3 seconds.

## Install

After unzipping, run:

```bash
python scripts/apply_live_shadow_ui_v1.py
python -m pytest tests/test_live_shadow_ui_v1.py -v

cd frontend
npm run build
```

Then restart the FastAPI backend serving the application.

## Safety

The UI is read-only for shadow strategy state. It does not expose start-order, paper-order or broker-order actions.
