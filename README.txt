MIDPOINT M1 — HILEGA REUSE PRE-FLIGHT

Purpose:
Inspect the current RB-ITOS-AI codebase and identify the exact Hilega Milega
frontend components, audit UI, API routes, replay paths, and Midpoint routes that
can be reused.

This is read-only. It changes nothing.

Run:
cd ~/RB-ITOS-AI
source .venv/bin/activate
export PYTHONPATH=backend

python scripts/midpoint_m1_hilega_reuse_preflight.py \
  | tee /tmp/midpoint-m1-hilega-reuse-preflight.txt

Then paste the output.
