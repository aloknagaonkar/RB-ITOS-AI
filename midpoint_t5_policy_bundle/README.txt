MIDPOINT T+5 INITIAL-RISK POLICY BACKTEST V1
============================================

Folder structure after installation
-----------------------------------
RB-ITOS-AI/
├── scripts/
│   └── backtest_midpoint_t5_initial_risk_v1.py
├── tests/
│   └── test_backtest_midpoint_t5_initial_risk_v1.py
└── midpoint_t5_policy_bundle/
    └── install.py

Prerequisite outputs
--------------------
Run MIDPOINT_ENTRY_HEALTH_V1 and the 490-session good/bad feature study first.

Install
-------
cd ~/RB-ITOS-AI
source .venv/bin/activate
python midpoint_t5_policy_bundle/install.py

Run
---
PYTHONPATH=backend:. python scripts/backtest_midpoint_t5_initial_risk_v1.py

Outputs
-------
data/historical-evidence/hilega-pcr-oi-support-research-v1/
midpoint-t5-initial-risk-policy-v1/
├── report.json
├── policy-summary.csv
├── policy-impact.csv
├── family-direction-breakdown.csv
└── trade-level-decisions.csv

Policy rules
------------
All rules apply only when the trade is active and has not reached +20 by the
completed exact T+5 candle.  A proof on T+5 bypasses the candidate.

* T5_PRICE_NON_PROGRESS: directional close progress <= 0.
* T5_DI_FAILURE_ZERO: directional DI spread <= 0.
* T5_COMBINED_EDGE_FAILURE_ZERO: intended-minus-opposite health edge <= 0.
* T5_PRICE_MOMENTUM_FAILURE: fast-EMA price momentum is false.
* T5_DI_AND_EDGE_FAILURE_ZERO: DI and combined edge both <= 0.
* T5_TWO_OF_THREE_FAILURE: at least two of DI, edge, momentum fail.
* T5_DI_EDGE_VWAP_FAILURE_ZERO: DI, edge and futures-VWAP change all <= 0.

Safety
------
Research only. Actual completed T+5 NIFTY close valuation. No live files,
services, audits, decisions, entries, exits, orders, paper orders or quantities
are modified.
