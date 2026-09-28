MIDPOINT M1.1 — EXACT SOURCE CAPTURE

This is the final read-only capture before the implementation patch.

Run:

cd ~/RB-ITOS-AI
source .venv/bin/activate
export PYTHONPATH=backend

python scripts/midpoint_m1_1_exact_source_capture.py \
  | tee /tmp/midpoint-m1-1-exact-source.txt

Paste the output.

No restart. No file mutation.
