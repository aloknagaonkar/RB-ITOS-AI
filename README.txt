B FAMILY — POST-PROOF TEMPORAL STABILITY DIAGNOSTIC V19
=========================================================

Purpose
-------
Check whether the V18 post-+20 runner-vs-nonrunner differences keep the same
direction through time.

Temporal views
--------------
1) First 60 / middle 60 / latest 60 framework sessions
2) Older 120 / latest 60

Fixed windows
-------------
+3m
+5m
+10m

Primary V18 features
--------------------
additional favorable expansion
net move from +20 at window end
directional VWAP change
ATR-normalized favorable expansion

No thresholds are selected.
No exit is changed.
No optimization is performed.

Run
---
cd ~/RB-ITOS-AI
source .venv/bin/activate
export PYTHONPATH=backend

python scripts/b_family_post_proof_temporal_stability_v19.py \
  | tee /tmp/b-family-post-proof-temporal-stability-v19.txt

Paste the complete output back.
