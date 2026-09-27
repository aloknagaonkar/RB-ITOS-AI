FAMILY C REJECTION AUDIT — 60 SESSIONS — V1
============================================

This audit compares the previous Family C population against the corrected V1.1
population.

Expected input files already produced by the prior runs:

OLD:
data/historical-evidence/hilega-pcr-oi-support-research-v1/
midpoint-vwap-setup-family-60-session-validation-v1/
setup-family-events-v1.csv

NEW:
data/historical-evidence/hilega-pcr-oi-support-research-v1/
midpoint-vwap-setup-family-60-session-validation-v1-1/
setup-family-events-v1-1.csv

For each rejected former-C event it records:
- original direction
- original boundary-break timestamp
- midpoint retest/reclaim/failure fields already present in old research output
- first opposite-structure termination timestamp
- would-be old C rebreak timestamp
- minutes from termination to would-be rebreak
- old causal MFE/MAE and +1/+3/+5/+10/+15 behavior
- whether a same-direction Family D subsequently appeared
- time from termination to that D event

It also compares retained C vs rejected former-C descriptively.

RUN
---
cd ~/RB-ITOS-AI
source .venv/bin/activate
export PYTHONPATH=backend

python scripts/midpoint_vwap_60_session_family_c_rejection_audit.py \
  | tee /tmp/midpoint-vwap-60-session-family-c-rejection-audit-v1.txt

Do not move to 120 sessions until this output is reviewed.

Research only:
- no Hilega change
- no Candidate A change
- no B/D change
- no runtime/execution/order change
- no threshold search
