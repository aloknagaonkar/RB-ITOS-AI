HILEGA EARLY-RISK REFINEMENT V2 — FLAT WAIT + HARD T+10 SUNSET
===============================================================

Purpose
-------
Compare three observation-only early-risk candidates against the unchanged
canonical Hilega lifecycle. WMA21 RSI flatness is neutral: it permits the
trade to wait for improvement and cannot by itself reject or exit a trade.
Every candidate is permanently disabled after T+10.

WMA states
----------

The three-candle regression slope is direction-normalized:

  SUPPORTING  directional slope > +0.10
  FLAT_WAIT   -0.10 <= directional slope <= +0.10
  OPPOSING    directional slope < -0.10

For bullish trades, positive slope is directional. For bearish trades,
negative slope is directional. FLAT_WAIT does not add to failure_count.

Folder structure after installation
-----------------------------------

RB-ITOS-AI/
├── scripts/
│   └── research_hilega_early_risk_refinement.py
├── tests/
│   └── test_research_hilega_early_risk_refinement.py
└── data/historical-evidence/
    └── hilega-early-risk-refinement-490-v2-flat-wait/

Candidates
----------

A_T5_SEVERE_FAILURE
  Exact T+5 only: directional close progress <= 0, causal running MFE < 5,
  and at least four health components fail. Flat WMA is not a failure.

B_T5_T10_PERSISTENT_FAILURE
  Both exact T+5 and T+10 must show non-positive progress and at least two
  failed health components. Running MFE at T+10 must remain below 10 points.
  Flat WMA is not a failure. Exit valuation is the exact observed T+10 close.

C_EARLY_PRICE_STRUCTURE_FAILURE
  At exact T+5 or T+10: non-positive progress, causal running MFE < 10,
  EMA/WMA ordering lost, EMA-WMA gap not expanding, and WMA slope strictly
  opposing the trade direction. Flat WMA cannot trigger Candidate C.

Evidence policy
---------------

The 480 frozen sessions are development evidence because their prior OOS
results have already been inspected. They are shown in three chronological
160-session blocks. The latest 10 already inspected sessions are labelled
OBSERVED_FORWARD, not untouched confirmation. Only new future sessions may
be used as the new untouched confirmation cohort.

Install
-------

  cd ~/RB-ITOS-AI
  source .venv/bin/activate
  python hilega_early_risk_refinement_bundle/install.py

Run
---

  PYTHONPATH=backend:. python \
    scripts/research_hilega_early_risk_refinement.py

Outputs
-------

  report.json
  policy-summary.csv
  outcome-matrix.csv
  trade-policy-comparison.csv
  candidate-exit-ledger.csv
  bad-trades-not-detected.csv
  checkpoint-values.csv
  wma-transition-summary.csv
  selected-date-checkpoints.csv
  top-decile-moves-destroyed.csv

The outcome files explicitly identify:

  BAD_TRADE_CORRECTLY_EXITED_EARLY
  BAD_TRADE_NOT_DETECTED
  GOOD_TRADE_RETAINED
  GOOD_TRADE_WRONGLY_EXITED_EARLY

They also report points saved on bad trades, points lost on good trades, net
point recovery, +20 moves destroyed, and top-decile moves destroyed.

Safety
------

Research only. No live strategy, service, audit, entry, exit, order, paper
order, or quantity is changed.
