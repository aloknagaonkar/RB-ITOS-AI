B FAMILY — POST-08-SEP UNSEEN VALIDATION READINESS AUDIT V9
===============================================================

Why this step exists
--------------------
The frozen canonical B research universe ends on 2026-09-08.

Before validating V8.2 on genuinely unseen sessions, we must know whether the
repo already contains all three required post-cutoff artifacts:

1. Underlying NIFTY 1m OHLC
2. Opening-candle midpoint framework events
3. NIFTY futures / session VWAP data

We must NOT hand-reconstruct B again.

Run
---
cd ~/RB-ITOS-AI
source .venv/bin/activate
export PYTHONPATH=backend

python scripts/b_family_post_08sep_readiness_audit_v9.py \
  | tee /tmp/b-family-post-08sep-readiness-audit-v9.txt

What to send back
-----------------
Paste the complete output.

If the audit shows common post-cutoff coverage, the next script will run the
frozen canonical B detector and the unchanged V8.2 risk models only on those
new sessions.

If one artifact is missing, the audit also lists the existing repository
generator scripts so we can produce it using frozen code rather than inventing
new semantics.
