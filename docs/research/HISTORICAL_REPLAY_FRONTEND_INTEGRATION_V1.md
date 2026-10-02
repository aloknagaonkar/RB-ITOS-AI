# Historical Replay Frontend Integration V1

This patch mounts the existing `HistoricalReplay` component into the current App.tsx
workspace navigation.

Changes are presentation/routing only:
- add "Historical replay" navigation item after Live shadow
- add a replay-specific page description
- suppress collection-control action button on the replay page
- render `<HistoricalReplay />`
- import the component

No trading logic, replay logic, strategy thresholds, or audit data are modified.

Apply:
```bash
python scripts/apply_historical_replay_frontend_integration_v1.py
python scripts/verify_historical_replay_frontend_integration_v1.py
```

Then build:
```bash
cd frontend
npm run build
cd ..
```
