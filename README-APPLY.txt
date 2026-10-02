LIVE FIXED SESSION UI V1

Copy additive files:
  cp backend/market_lab/live_fixed_session_ui_projection_v1.py backend/market_lab/
  cp tests/test_live_fixed_session_ui_projection_v1.py tests/
  cp scripts/apply_live_fixed_session_ui_v1.py scripts/
  cp docs/research/LIVE_FIXED_SESSION_UI_V1.md docs/research/

Apply:
  python scripts/apply_live_fixed_session_ui_v1.py

Test:
  python -m pytest \
    tests/test_live_fixed_session_anchor_recovery_v1.py \
    tests/test_live_fixed_session_ui_projection_v1.py -v

Compile:
  python -m py_compile \
    backend/market_lab/live_fixed_session_ui_projection_v1.py \
    backend/market_lab/api.py

Build frontend:
  cd frontend && npm run build && cd ..

Restart:
  ./scripts/restart.sh

Verify latest state:
  curl -s http://127.0.0.1:8123/api/state | python -c 'import sys,json;d=json.load(sys.stdin);x=d["history"][-1];print(json.dumps({"id":x["id"],"fixed_session_ui":x.get("fixed_session_ui"),"fixed_session_trends":x.get("fixed_session_trends")},indent=2))'

Verify latest observation detail:
  ID=$(curl -s http://127.0.0.1:8123/api/state | python -c 'import sys,json;d=json.load(sys.stdin);print(d["history"][-1]["id"])')
  curl -s "http://127.0.0.1:8123/api/observations/$ID" | python -c 'import sys,json;d=json.load(sys.stdin);print(json.dumps(d.get("fixed_session_ui"),indent=2))'

Temporary backups created by patcher:
  backend/market_lab/api.py.pre-fixed-session-ui-v1
  frontend/src/App.tsx.pre-fixed-session-ui-v1

Do NOT stage backups.
Do NOT use git add .
Do not commit until tests/build/API/UI verification pass.
