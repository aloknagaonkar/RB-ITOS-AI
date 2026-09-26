# Candidate A Block Stability V1

This uses the **full 180-session Candidate A dataset** and then slices those same sessions into the existing 20-session blocks only to test temporal stability.

It does **not** reduce the analysis to 20 sessions.

Primary result remains all 180 sessions. Block results answer: does the same behavior repeat across time?

It reports:

- full 180 bearish / bullish / combined Candidate A
- Candidate A performance in TRAIN + OOS_A ... OOS_H
- distance buckets within every block
- recent VWAP touch-age buckets within every block
- simple cross-block consistency counts

No threshold search and no Candidate A change.

## Run

Copy `midpoint_vwap_candidate_a_block_stability.py` into `~/RB-ITOS-AI/scripts/`.

```bash
cd ~/RB-ITOS-AI
source .venv/bin/activate
export PYTHONPATH=backend

python scripts/midpoint_vwap_candidate_a_block_stability.py \
  | tee /tmp/midpoint-vwap-candidate-a-block-stability.txt
```
