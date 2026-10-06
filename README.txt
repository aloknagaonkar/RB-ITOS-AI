HILEGA LIVE SESSION STATUS FIX

Copy the backend/, frontend/, and tests/ files in this package into the root of
your project, allowing them to replace the files at those paths.

Changed files:
  backend/market_lab/hilega_directional_live_shadow_ui_v1.py
  frontend/src/hilegaMilegaShadow.tsx
  tests/test_hilega_directional_live_shadow_ui_v1.py

The live status API previously used the last audit state across all dates as
today's state. After the 14:55 cutoff, that could make yesterday's
SESSION_LOCKED appear current the next morning. This fix scopes the state card
to today's date in India Standard Time, while retaining saved audit and trade
records. Their timestamps are shown so prior-session data is not mistaken for
today's activity. When no decision has arrived for today, the page warns and
identifies the date of the last recorded state.

The fix does not start the live worker or restore missing market data. If the
warning still appears after applying the files, check that today's worker
bootstrap completed and the current market-data feed is producing bars.
Execution and paper orders remain disabled.

From the project root, run:
  python -m pytest tests/test_hilega_directional_live_shadow_ui_v1.py -q
