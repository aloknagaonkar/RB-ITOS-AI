HILEGA WMA POSITIVE-DIRECTION RESEARCH — 490 SESSIONS
====================================================

Purpose
-------
Determine when a rising/falling WMA21 of RSI9 actually supports profitable
Hilega trades.  This specifically tests the observed failure where a bullish
entry had WMA21 change near +0.57 but lost points because RSI was below 50 and
the EMA-WMA gap was contracting.

Folder structure
----------------
Place this folder directly inside RB-ITOS-AI:

RB-ITOS-AI/
├── hilega_wma_positive_direction_bundle/
│   ├── install.py
│   ├── README.txt
│   └── files/
│       ├── scripts/research_hilega_wma_positive_direction.py
│       └── tests/test_research_hilega_wma_positive_direction.py
├── scripts/
├── tests/
└── data/

Install
-------
cd ~/RB-ITOS-AI
source .venv/bin/activate
python hilega_wma_positive_direction_bundle/install.py

Run
---
PYTHONPATH=backend:. python scripts/research_hilega_wma_positive_direction.py

Input
-----
data/historical-evidence/hilega-alignment-points-490-v1/
trade-alignment-points.csv

If this input is missing, run the existing 490-session alignment/points
materialization first.

Output
------
data/historical-evidence/hilega-wma-positive-direction-490-v1/
├── report.json
├── wma-slope-band-summary.csv
├── wma-slope-band-by-route.csv
├── wma-context-combinations.csv
├── wma-threshold-profile-scan.csv
├── is-ranked-profiles-with-holdouts.csv
└── trade-wma-direction-evidence.csv

What is tested
--------------
1. Direction-normalized WMA slope bands from adverse through >1.00.
2. WMA slope alone.
3. WMA plus RSI on the intended side of 50.
4. WMA plus EMA-WMA alignment.
5. WMA plus an expanding directional EMA-WMA gap.
6. WMA + RSI50 + aligned and expanding gap.
7. Full directional alignment including RSI and EMA slopes.

Validation discipline
---------------------
- First 480 sessions are frozen history.
- First 70% of frozen history is IS.
- Last 30% of frozen history is untouched OOS.
- Latest 10 sessions are a separate forward block.
- Profiles are ranked only from IS. OOS and forward results are attached after
  selection and never used to choose the rule.
- All inputs are measured on the completed entry candle.

Safety
------
Research only. No live gate, strategy decision, service, audit, order, paper
order, quantity or execution setting is changed.
