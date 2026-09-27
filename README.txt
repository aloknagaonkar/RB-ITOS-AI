B FAMILY — POST-PROOF EXPANSION DIAGNOSTIC V18
================================================

Purpose
-------
Compare causal behavior shortly after +20 proof between:

- B events that later become >=75-point canonical runners
- B events that reach +20 but never reach +75

Fixed observation windows:
- +3 minutes
- +5 minutes
- +10 minutes

Features
--------
additional favorable expansion after proof
maximum pullback from +20 proof
net move at window end
advancing-close percentage
confirmed 1m swing count
supportive advancing swing count
directional futures-VWAP distance and change
ATR-normalized expansion
ATR-normalized pullback

Important
---------
Future >=75 is only an outcome label. It is not used to create the features.

No cutoff is selected.
No exit is changed.
No optimization is performed.

Run
---
cd ~/RB-ITOS-AI
source .venv/bin/activate
export PYTHONPATH=backend

python scripts/b_family_post_proof_expansion_diagnostic_v18.py \
  | tee /tmp/b-family-post-proof-expansion-v18.txt

Paste the complete output back.
