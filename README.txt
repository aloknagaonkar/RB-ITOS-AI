MIDPOINT V60 — POST-REENTRY SECOND-LEG AUDIT

Purpose:
Keep all existing re-entry timestamps frozen and measure what the second leg
actually does before structural terminal/session end.

Run:

cd ~/RB-ITOS-AI
source .venv/bin/activate
export PYTHONPATH=backend

python scripts/midpoint_v60_post_reentry_second_leg_audit.py

cat \
data/historical-evidence/hilega-pcr-oi-support-research-v1/\
midpoint-v60-post-reentry-second-leg-audit/summary-v60.txt

Outputs:
- second-leg-cases-v60.csv
- report-v60.json
- summary-v60.txt

No restart required. No strategy rule changes.
