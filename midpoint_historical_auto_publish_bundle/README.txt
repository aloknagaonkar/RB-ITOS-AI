MIDPOINT HISTORICAL REPLAY AUTO-PUBLISHER

Folder structure after extracting into ~/RB-ITOS-AI:

  midpoint_historical_auto_publish_bundle/
  ├── install.py
  └── files/
      ├── scripts/midpoint_append_live_dates_to_replay.py
      ├── scripts/midpoint_auto_publish_historical.py
      ├── scripts/restart.sh
      ├── scripts/stop.sh
      ├── scripts/status.sh
      └── tests/test_midpoint_auto_publish_historical.py

Install:

  cd ~/RB-ITOS-AI
  source .venv/bin/activate
  python midpoint_historical_auto_publish_bundle/install.py

Backfill every completed audited date currently missing from replay:

  PYTHONPATH=backend:. python scripts/midpoint_auto_publish_historical.py --once

Enable automatic 15-minute checks:

  ./scripts/restart.sh
  ./scripts/status.sh

Check publisher activity:

  tail -n 100 data/logs/midpoint-historical-publisher.log

Expected behavior:

- A live session is ineligible on its own IST trading date.
- It becomes eligible on the next IST calendar day.
- Publication requires 360 exact paired market minutes and audit safety/parity.
- Provider-revised candles remain labelled; original live decisions are retained.
- Manifest publication is atomic and no live strategy decision is changed.
