B FAMILY — 60-SESSION RECOVERY-WINDOW VALIDATION V3
=====================================================

Tests 1m / 2m / 3m / 5m causal waiting windows after the first B warning.

Run:
cd ~/RB-ITOS-AI
source .venv/bin/activate
export PYTHONPATH=backend

python scripts/b_family_60_session_recovery_window_v3.py \
  | tee /tmp/b-family-60-session-recovery-window-v3.txt

Requires:
- V2 warning/recovery CSV already generated.

Outputs:
data/historical-evidence/hilega-pcr-oi-support-research-v1/
  b-family-60-session-recovery-window-v3/
    b-family-recovery-window-events-v3.csv
    b-family-recovery-window-summary-v3.txt

Research only.
Frozen B entry logic is unchanged.
No execution/runtime changes.
