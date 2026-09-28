B FAMILY — V31 DEGRADED-STATE / FAILED-RECOVERY DIAGNOSTIC
============================================================

Purpose
-------
Treat the rejected V29 signal as a DEGRADED-state trigger, not an exit.

For each of the 7 V29 OOS runner events, follow the degraded state until:
A) price retakes the V29 episode-start directional close level -> RECOVERED
or
B) canonical structural invalidation occurs first -> FAILED_RECOVERY

Measure:
- degraded-state duration
- worst directional damage
- damage / running MFE
- VWAP path
- recovery-attempt count
- highest recovery attempt
- gap to target
- improving vs weakening recovery attempts

No threshold search.
No exit rule.
No Family-B change.
No V20 change.

Run:

cd ~/RB-ITOS-AI
source .venv/bin/activate
export PYTHONPATH=backend

python scripts/b_family_degraded_state_path_diagnostic_v31.py \
  | tee /tmp/b-family-degraded-state-v31.txt

Paste the complete V31 output back.
