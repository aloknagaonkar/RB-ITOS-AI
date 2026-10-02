HILEGA SAME-PAGE HISTORICAL REPLAY BUNDLE
==========================================

Purpose
-------
Adds Live shadow / Historical replay modes to the existing Hilega-Milega page.
Historical sessions reuse recorded strategy audit and market evidence. Completed
directional live sessions appear automatically when the 14:55 cutoff is audited;
there is no copying daemon and no duplicate session publication.

Folder structure installed
--------------------------
backend/market_lab/
  hilega_historical_ui_api_v1.py
  hilega_directional_candle_ui_v1.py
  hilega_directional_historical_ui_v1.py
frontend/src/
  hilegaMilegaShadow.tsx
  hilegaHistoricalReplay.tsx
docs/
  HILEGA_DIRECTIONAL_STRATEGY_VALIDATION.md
tests/
  test_hilega_live_session_visibility_v1.py
  test_hilega_directional_candle_ui_v1.py
  test_hilega_directional_historical_ui_v2.py
  test_hilega_same_page_historical_replay.py

Install and validate
--------------------
cd ~/RB-ITOS-AI
source .venv/bin/activate
python hilega_same_page_historical_replay_bundle/install.py

Activate the API/UI source after PASS
-------------------------------------
./scripts/restart.sh
./scripts/status.sh

Quick verification
------------------
curl -fsS \
  http://127.0.0.1:8123/api/live-shadow/hilega-historical/sessions |
python -c '
import json,sys
x=json.load(sys.stdin)
for row in x["sessions"][:10]:
    print(row["session_date"], row["status"], row["source"], row["evidence_level"])
'

Open the Hilega-Milega page and choose Historical replay. Selecting a date loads
it immediately. Current/PARTIAL sessions refresh every 60 seconds. COMPLETE
sessions are treated as immutable.

Safety
------
This bundle does not change entry/exit rules, strategy state, worker selection,
execution, paper orders, quantity, live audit or option evidence. Missing
historical evidence remains explicitly unavailable and is never synthesized.

