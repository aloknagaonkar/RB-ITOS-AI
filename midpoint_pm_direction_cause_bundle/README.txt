MIDPOINT PM DIRECTION-CAUSE RESEARCH V1
=======================================

Folder structure after extracting/copying into the repository root:

  RB-ITOS-AI/
    midpoint_pm_direction_cause_bundle/
      install.py
      files/
        scripts/
          backtest_midpoint_pm_be.py
          research_pm_direction_cause.py
        tests/
          test_backtest_midpoint_pm_be.py
          test_research_pm_direction_cause.py

Install and validate:

  cd ~/RB-ITOS-AI
  source .venv/bin/activate
  python midpoint_pm_direction_cause_bundle/install.py

Regenerate the enriched 480 + 14-forward-session PM trade evidence:

  PYTHONPATH=backend:. python \
    scripts/backtest_midpoint_pm_be.py \
    --include-forward

Run the cause diagnostic:

  PYTHONPATH=backend:. python \
    scripts/research_pm_direction_cause.py

Main output:

  data/historical-evidence/hilega-pcr-oi-support-research-v1/
    pm-direction-cause-v1/
      report.json
      trade-diagnostics.csv
      route-summary.csv
      block-summary.csv
      split-summary.csv
      proof-summary.csv
      feature-summary.csv
      outlier-concentration.csv

What this answers:

  * Is PM_B bearish profit stable across chronological blocks and OOS?
  * Is performance concentrated in one or three outlier trades?
  * Which exit route produces the gain or loss in each family/direction?
  * Do losers differ in directional futures-VWAP, PM range, timing, or delay?
  * Are PM_E losses mostly unproved structural-baseline trades?

The decision gate cannot enable anything. It returns HOLD_RESEARCH unless all
predeclared robustness checks pass. No threshold search is performed.

Safety: read only; no live config, service restart, audit mutation, order,
paper order, quantity, or PM live gate change.
