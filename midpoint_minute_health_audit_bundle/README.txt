MIDPOINT MINUTE HEALTH AUDIT
============================

Folder structure
----------------
  RB-ITOS-AI/
  ├── midpoint_minute_health_audit_bundle/
  │   ├── install.py
  │   └── files/
  ├── backend/
  ├── frontend/
  ├── tests/
  └── scripts/

Install and restart
-------------------
  cd ~/RB-ITOS-AI
  source .venv/bin/activate
  git pull
  python midpoint_minute_health_audit_bundle/install.py
  ./scripts/restart.sh
  ./scripts/status.sh

What changes
------------
* Writes one presentation-only market-health snapshot per completed minute to:
    data/live-observation/midpoint-strategy-v1/market-health.jsonl
* Adds one row per completed minute to Midpoint candle-by-candle decision audit,
  even when no strategy signal is generated.
* The minute row uses the existing columns and shows the same bullish and
  bearish health fields already used by signal rows.
* Existing Continuous market health, Directional trade health, signal rows,
  Inspect decision behavior, columns and recorded data remain unchanged.

Important
---------
Minute history starts after the post-install restart. Existing immutable audit
events remain visible, but earlier minutes cannot be reconstructed from the
replaceable latest-heartbeat file.

Safety
------
This is presentation and observation evidence only. It cannot create or change
an entry, exit, order, paper order, quantity, or immutable strategy decision.
