Copy the script to ~/RB-ITOS-AI/scripts/ and run:

cd ~/RB-ITOS-AI
source .venv/bin/activate
export PYTHONPATH=backend
python scripts/midpoint_vwap_delayed_and_rebreak_research.py \
  | tee /tmp/midpoint-vwap-delayed-and-rebreak-research.txt

Research only. Candidate A/Hilega/runtime/execution remain unchanged.

25 Aug Study A RED sanity target:
T0 09:39, Candidate A=False, delayed bearish VWAP confirmation around 09:42,
delay=3m, confirmation VWAP distance about -8.31.

Study B should expose the later midpoint/reclaim/rebreak sequence for manual review.
