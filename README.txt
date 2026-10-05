HILEGA HISTORICAL REPLAY 404 FIX

Copy the backend/, frontend/, and tests/ files in this package into the root of
your project, allowing these files to replace the existing files at those paths.

Changed files:
  backend/market_lab/hilega_historical_ui_api_v1.py
  frontend/src/hilegaHistoricalReplay.tsx
  frontend/vite.config.ts
  tests/test_hilega_historical_ui_api_v1.py
  tests/test_hilega_same_page_historical_replay.py

This corrects the misleading WMA-gap error shown when canonical Hilega v1
evidence is missing, and displays API error details as plain text. It does not
create replay data or substitute recorded live trades. The selected date will
remain unavailable for V1/V2 until its canonical trade row is present in the
published frozen or forward-confirmation evidence.

From the project root, run the focused regression tests:
  python -m pytest tests/test_hilega_same_page_historical_replay.py tests/test_hilega_historical_ui_api_v1.py tests/test_hilega_wma_gap_historical_v1.py -q

For the UI, start the backend API on port 8123 in one terminal:
  python -m market_lab.runtime api

Then start the frontend in another terminal:
  npm --prefix frontend run dev

To invoke the Hilega-Milega historical replay CLI directly (requires the
project environment and an Upstox access token in .env):
  PYTHONPATH=backend python -m market_lab.hilega_milega_historical_replay_cli_v1 --dates YYYY-MM-DD

The Vite proxy change fixes frontend API requests in development mode. These
changes do not alter strategy rules or historical replay calculations.
