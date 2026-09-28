MIDPOINT V59 — POST-RESCUE RE-ENTRY AUDIT

Purpose:
Audit only the existing post-CAP20 re-entry cases from the 480-session replay.

Run:

cd ~/RB-ITOS-AI
source .venv/bin/activate
export PYTHONPATH=backend

python scripts/midpoint_v59_post_rescue_reentry_audit.py

cat \
data/historical-evidence/hilega-pcr-oi-support-research-v1/\
midpoint-v59-post-rescue-reentry-audit/summary-v59.txt

Outputs:
- reentry-cases-v59.csv
- report-v59.json
- summary-v59.txt

No live restart required. No strategy rule changes.
