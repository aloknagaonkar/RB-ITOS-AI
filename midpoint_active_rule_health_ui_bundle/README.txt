MIDPOINT ACTIVE-RULE + HEALTH UI
================================

Folder placement:

RB-ITOS-AI/
├── midpoint_active_rule_health_ui_bundle/
│   ├── install.py
│   └── files/
├── frontend/
└── tests/

Install and build:

  cd ~/RB-ITOS-AI
  source .venv/bin/activate
  python midpoint_active_rule_health_ui_bundle/install.py

What changes
------------
* Audit combines Owner/Direction and State/Result.
* Six-step Current Active Rule strip replaces three card-heavy grids.
* Directional Health shows the three core votes separately from supporting
  evidence and context.
* Summary cards are reduced from six to four.
* Inspect Decision remains the single detailed audit action.

The installer builds frontend/dist.  API and workers are not restarted.
No strategy, entry, exit, audit, order, quantity, or safety setting changes.

