# Hilega session-centric/live integration v2 (cumulative)

Use this version if your current `hilegaDecisionTable.tsx` hash is:

`43c668909d8019bf495d01e3d2529a4c4c69770452694e5faf6c3d365b4f8f38`

That is the progressive CE/no-lookahead version. This cumulative installer
upgrades it to the linked CE lifecycle version first and then installs the
session-centric Historical Replay/live availability integration in one safe step.

Install:

```bash
unzip hilega-session-centric-live-integration-v2.zip -d /tmp/
cd ~/RB-ITOS-AI
source .venv/bin/activate

python /tmp/hilega-session-centric-live-integration-v2/install.py   --repo "$PWD" --check
```

If CHECK PASS:

```bash
python /tmp/hilega-session-centric-live-integration-v2/install.py   --repo "$PWD" --apply

node tests/test_hilega_decision_table_v1.cjs

PYTHONPATH=backend pytest -q   tests/test_hilega_historical_ui_api_v1.py   tests/test_hilega_session_replay_api_v1.py

cd frontend
npm run build
cd ..
```

Backend API restart is required after successful tests/build. Do not restart the
Hilega live-shadow worker just for this API/UI patch.
