B FAMILY — V32 MULTI-BLOCK DEGRADED-STATE POPULATION STUDY
=============================================================

Purpose
-------
Expand V31 across existing historical blocks.

Frozen semantics:
- Family-B entry unchanged
- V20 runner classifier unchanged
- V29 remains rejected as an exit
- V29-type signal is only a DEGRADED-state trigger

For every RUNNER_STRENGTHENING event with raw data available:
- detect first V29-type degradation after classification
- follow until price retakes episode-start level -> RECOVERED
  or structural invalidation -> FAILED_RECOVERY
- compare duration, damage, normalized damage, recovery attempts,
  target gap, and VWAP path

No threshold search.
No exit rule.

Run:

cd ~/RB-ITOS-AI
source .venv/bin/activate
export PYTHONPATH=backend

python scripts/b_family_degraded_state_population_v32.py \
  | tee /tmp/b-family-degraded-state-population-v32.txt

Important
---------
This script auto-discovers prior B-event CSVs and historical raw sidecars.
If it reports skipped_missing_raw > 0, paste the complete output before
creating more data. We should inspect which blocks are missing rather than
silently substituting or reconstructing data.

Paste the complete V32 output back.
