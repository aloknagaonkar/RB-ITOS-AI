MIDPOINT SESSION HEALTH DIAGNOSTIC V1
=====================================

Folder placement
----------------
Copy midpoint_session_health_diagnostic_bundle into the RB-ITOS-AI repository
root, next to scripts/, backend/, frontend/, and tests/.

Install
-------
  cd ~/RB-ITOS-AI
  source .venv/bin/activate
  python midpoint_session_health_diagnostic_bundle/install.py

Run September 30
----------------
  PYTHONPATH=backend:. python \
    scripts/diagnose_midpoint_session_health.py \
    --session-date 2026-09-30

Output
------
  data/historical-evidence/hilega-pcr-oi-support-research-v1/
    midpoint-session-health-diagnostic-v1/2026-09-30/
      report.json
      summary.csv
      market-minutes.jsonl

The script prints PREENTRY, ENTRY, T3, T5, PROOF and CLASSIFIER health when
those checkpoints exist. It also reports the T+5 initial-risk candidate and
the exact NORMAL_B dual-failure classifier-close counterfactual.

Safety and interpretation
-------------------------
- Read only: no service restart required.
- No live audit, configuration, entry, exit, order or quantity is changed.
- Provider historical candles may contain post-session revisions. The report
  explicitly records the difference from the immutable live entry price.
- Existing diagnostic output is immutable. Use a new --output-root to rerun.
