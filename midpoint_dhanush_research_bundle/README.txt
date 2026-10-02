DHANUSH HISTORICAL RESEARCH
===========================

Folder placement:

  ~/RB-ITOS-AI/midpoint_dhanush_research_bundle/

Install without restarting services:

  cd ~/RB-ITOS-AI
  source .venv/bin/activate
  python midpoint_dhanush_research_bundle/install.py

Run the 480-session scan:

  PYTHONPATH=backend:. python scripts/midpoint_dhanush_historical_scan.py

Outputs:

  data/historical-evidence/hilega-pcr-oi-support-research-v1/
  midpoint-dhanush-v1/report.json
  midpoint-dhanush-v1/matches.csv

Frozen V1 definition:

  - origin: B or E entry and its original midpoint
  - completed 5-minute candles
  - midpoint approach zone: +/- 10 NIFTY points
  - adjacent candles in the zone form one attempt
  - a new attempt requires price to move away from the zone first
  - attempts 1 and 2 reject without a completed close across midpoint
  - attempt 3 confirms on a completed close across exact midpoint
  - bullish and bearish definitions are symmetric

Research only. No live configuration, worker, API, audit, order, or quantity is
changed by the installer or scanner.
