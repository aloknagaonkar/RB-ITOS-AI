B FAMILY — 60-SESSION WARNING / RECOVERY ANALYSIS V2
======================================================

Run after V1:

cd ~/RB-ITOS-AI
source .venv/bin/activate
export PYTHONPATH=backend

python scripts/b_family_60_session_warning_recovery_v2.py \
  | tee /tmp/b-family-60-session-warning-recovery-v2.txt

Outputs:
data/historical-evidence/hilega-pcr-oi-support-research-v1/
  b-family-60-session-warning-recovery-v2/
    b-family-warning-recovery-events-v2.csv
    b-family-warning-recovery-summary-v2.txt

Measures:
- entry -> warning time
- warning -> recovery time
- warning -> invalidation time
- points at warning/recovery/invalidation
- post-warning MFE / MAE
- post-recovery MFE
- whether recovery creates a new favorable extreme

Research only. Frozen B entry definition remains unchanged.
