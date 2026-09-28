MIDPOINT M2.2 — FULL-DAY DATE-WISE REPLAY + INSPECT DRAWER

What this changes
- Historical replay materializes the available full-day minute stream for each tested session.
- One selected trading date is loaded at a time.
- Strategy events are overlaid on exact minute rows.
- Inspect opens a fixed audit drawer immediately instead of rendering below the table.
- Previous date / Next date navigation is added.
- Fresh Candidate A is displayed as owner FRESH A without mutating the raw audit family.
- Live remains limited to current + previous available trading session.
- Observation-only/execution-disabled safety is unchanged.

Files changed
- backend/market_lab/midpoint_strategy/live_shadow_ui.py
- scripts/midpoint_m2_materialize_historical_replay.py
- frontend/src/midpointStrategyShadow.tsx
- frontend/src/midpointStrategyShadow.css

Apply
  unzip midpoint_m2_2_full_day_replay_ui.zip -d /tmp/midpoint_m2_2
  cd ~/RB-ITOS-AI
  source .venv/bin/activate
  export PYTHONPATH=backend
  python /tmp/midpoint_m2_2/scripts/apply_midpoint_m2_2_full_day_replay_ui.py

Focused tests
  cp /tmp/midpoint_m2_2/tests/test_midpoint_m2_2_full_day_replay_ui.py tests/
  python -m pytest \
    tests/test_midpoint_m3_1_query_defaults.py \
    tests/test_midpoint_m3_live_shadow_ui.py \
    tests/test_midpoint_m2_live_replay_ui.py \
    tests/test_midpoint_m2_2_full_day_replay_ui.py -v

Full midpoint suite
  python -m pytest tests -q -k 'midpoint' --disable-warnings

Materialize the same 3 sample sessions with full minute rows
  python scripts/midpoint_m2_materialize_historical_replay.py --limit 3

Then inspect manifest and one date before materializing all sessions.

Frontend
  cd frontend
  npm run build

Only the API process needs restarting after backend/static changes.
Do not restart or kill live_shadow_worker_v1.
