SEPTEMBER 9-29 FORWARD-OOS DATA UPDATE
======================================

Install from the RB-ITOS-AI repository root:

  source .venv/bin/activate
  python midpoint_sep_forward_data_bundle/install.py

Materialize 14 exact trading sessions:

  PYTHONPATH=backend:. python \
    scripts/materialize_midpoint_forward_market_data.py

Run the frozen 480 sessions plus the 14-session forward block:

  PYTHONPATH=backend:. python \
    scripts/backtest_midpoint_pm_be.py --include-forward

Forward evidence:

  data/historical-evidence/hilega-pcr-oi-support-research-v1/
    midpoint-forward-oos-2026-09-09-to-29-v2/

Backtest results:

  data/historical-evidence/hilega-pcr-oi-support-research-v1/
    midpoint-pm-be-backtest-480-plus-forward-corrected-v2/report.json
    midpoint-pm-be-backtest-480-plus-forward-corrected-v2/pm-trades.csv

The frozen 480-session evidence is never changed. No live gates or services are
changed or restarted.

Important: the earlier v1 forward block that selected the October future for
September 28-29 is provisional and must not be used. This v2 bundle pins the
September 29 future (NSE_FO|68407) for the complete September 9-29 block.
The pinned key is read through Upstox's V3 historical-candle transport because
the expired-instrument transport may return HTTP 400 immediately after expiry.
