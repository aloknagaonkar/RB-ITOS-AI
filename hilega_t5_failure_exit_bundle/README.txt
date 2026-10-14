HILEGA T+5 FAILURE EXIT RESEARCH — 490 SESSIONS
================================================

Purpose
-------
Compare the unchanged Hilega exit lifecycle against two causal early-failure
exit candidates:

1. T5_IMMEDIATE_FAILURE
2. T5_TWO_CLOSE_FAILURE

The goal is to retain major moves while reducing quick post-entry reversals.

Folder structure
----------------
Place this folder directly inside RB-ITOS-AI:

RB-ITOS-AI/
├── hilega_t5_failure_exit_bundle/
│   ├── install.py
│   ├── README.txt
│   └── files/
│       ├── scripts/research_hilega_t5_failure_exits.py
│       └── tests/test_research_hilega_t5_failure_exits.py
├── scripts/
├── tests/
└── data/

Prerequisite
------------
These existing 490-session files must be available:

data/historical-evidence/hilega-alignment-points-490-v1/
├── trade-alignment-points.csv
└── trade-health-timeline.csv

Install
-------
cd ~/RB-ITOS-AI
source .venv/bin/activate
python hilega_t5_failure_exit_bundle/install.py

Run
---
PYTHONPATH=backend:. python scripts/research_hilega_t5_failure_exits.py

Rules
-----
An evaluated completed candle is unhealthy when:

1. Directional close points from entry are <= 0, and
2. At least two of five components fail:
   - EMA/WMA ordering
   - RSI slope
   - EMA slope
   - WMA slope
   - EMA-WMA gap expansion

T5_IMMEDIATE_FAILURE evaluates only the exact next completed 5-minute candle.

T5_TWO_CLOSE_FAILURE starts at T+5 and requires two consecutive unhealthy
completed candles. A healthy candle resets its counter.

The current structural exit has priority when it occurs on the same candle.
Candidate exit value is always the observed completed candle close.

Output
------
data/historical-evidence/hilega-t5-failure-exits-490-v1/
├── report.json
├── policy-summary.csv
├── trade-policy-comparison.csv
├── failure-component-summary.csv
└── selected-date-details.csv

The selected-date file contains detailed results for 30 September and
1 October by default.

Validation
----------
- 480 frozen sessions: 336 IS and 144 OOS.
- Latest 10 sessions: separate forward block.
- Large-move thresholds are learned only from IS.
- Output reports improved, equal and harmed trades; harmed control winners;
  and how many top-decile large moves each candidate exited early.

Safety
------
Research only. No live strategy, entry, exit, service, audit, order, paper
order, quantity or execution setting is changed.

