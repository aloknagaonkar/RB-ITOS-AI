MIDPOINT HISTORICAL HEALTH REPLAY BUNDLE
=========================================

Place this folder directly under the RB-ITOS-AI repository root:

RB-ITOS-AI/
├── midpoint_historical_health_bundle/
│   ├── install.py
│   └── files/
├── backend/
├── frontend/
├── scripts/
└── tests/

Install and validate source only:

  cd ~/RB-ITOS-AI
  source .venv/bin/activate
  python midpoint_historical_health_bundle/install.py

Materialize health for every replay session:

  PYTHONPATH=backend:. python scripts/materialize_midpoint_historical_health.py

Or materialize selected sessions:

  PYTHONPATH=backend:. python scripts/materialize_midpoint_historical_health.py \
    --dates 2026-09-29 2026-09-30

Existing trade-health.jsonl files are preserved unless --force is supplied.
The command never rewrites audit.jsonl or minutes.jsonl.

After materialization, restart the API/dashboard at a safe time:

  ./scripts/restart.sh
  ./scripts/status.sh

Future completed live days are published on the following IST date.  The
historical publisher now creates trade-health.jsonl immediately after the
validated replay session is published.

Safety
------
Observation only. Execution remains false, paper orders remain false,
quantity remains None, and no live lifecycle decision is changed.

