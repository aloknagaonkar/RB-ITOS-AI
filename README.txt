MIDPOINT V61 — RE-ENTRY NECESSITY / SECOND-LEG EXIT POLICY COMPARISON

Purpose:
Answer the exact question: is post-CAP20 re-entry actually needed?

The comparison keeps:
- B/E entries fixed
- CAP20 rescue fixed
- existing re-entry timestamps fixed

Policies:
A. CAP20 only, no re-entry
B. Current re-entry, structural terminal (session-end mark for open cases)
C. Same re-entry + protect +10 after +20 proof
D. Same re-entry + protect +20 after +30 proof
E. Same re-entry + breakeven after +20 proof
F. Same re-entry + 20-point trail after +20 proof

The protected policies are exploratory screens only. Do not select one for live
use from 9 re-entry cases alone.

Run:

cd ~/RB-ITOS-AI
source .venv/bin/activate
export PYTHONPATH=backend

python scripts/midpoint_v61_reentry_necessity_exit_policy_comparison.py

cat \
data/historical-evidence/hilega-pcr-oi-support-research-v1/\
midpoint-v61-reentry-necessity-exit-policy-comparison/summary-v61.txt

No restart required. No live mutation.
