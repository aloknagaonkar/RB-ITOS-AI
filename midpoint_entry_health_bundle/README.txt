MIDPOINT_ENTRY_HEALTH_V1 — RESEARCH ONLY
========================================

Folder structure after installation
-----------------------------------
RB-ITOS-AI/
├── scripts/
│   └── research_midpoint_entry_health_v1.py
├── tests/
│   └── test_research_midpoint_entry_health_v1.py
└── midpoint_entry_health_bundle/
    └── install.py

Install
-------
cd ~/RB-ITOS-AI
source .venv/bin/activate
python midpoint_entry_health_bundle/install.py

Run the fixed 490-session study
-------------------------------
PYTHONPATH=backend:. python scripts/research_midpoint_entry_health_v1.py

Outputs
-------
data/historical-evidence/hilega-pcr-oi-support-research-v1/
midpoint-entry-health-490-v1/
├── report.json
├── trade-health-features.csv
├── morning-trade-health.csv
├── pm-trade-health.csv
├── feature-statistics.csv
└── is-ranked-features.csv

Scope and safety
----------------
* 480 frozen sessions plus the latest 10 forward sessions.
* First 336 frozen sessions are IS; last 144 frozen sessions are OOS.
* The 10 forward sessions remain a separate confirmation segment.
* Completed one-minute candles and previously completed five-minute buckets only.
* No threshold, entry veto, exit, live gate, service restart or order change.
* observation_only=true, execution=false, paper=false, quantity=None.

Interpretation order
--------------------
1. Inspect is-ranked-features.csv to identify stable causal features.
2. Lock one small health rule using IS only.
3. Test the locked rule once on OOS and then forward.
4. Measure saved baseline loss and prematurely stopped +20 winners.
5. Only then add the rule as an observation-only live candidate.
