# Hilega active live-session visibility patch

Purpose:
- expose the active current trading day in `/api/live-shadow/hilega-historical/sessions`
- label it `LIVE` + `PARTIAL`
- keep existing completion behavior for now
- preserve source precedence, audit evidence, and strategy logic

Files:
- `install.py`
- `files/tests/test_hilega_live_session_visibility_v1.py`

The installer changes only:
`backend/market_lab/hilega_historical_ui_api_v1.py`

The added pytest is copied manually by the commands in ChatGPT's instructions or can be copied from the patch payload.
