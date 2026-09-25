Hilega Directional Option Recovery V1

Contains:
  backend/market_lab/hilega_directional_option_recovery_v1.py

From the RB-ITOS-AI repository root:
  unzip -o hilega_directional_option_recovery_patch.zip -d ~/RB-ITOS-AI
  cd ~/RB-ITOS-AI
  source .venv/bin/activate
  export PYTHONPATH=backend

Compile:
  python -m py_compile backend/market_lab/hilega_directional_option_recovery_v1.py

Dry-run only:
  python -m market_lab.hilega_directional_option_recovery_v1 \
    --session 2026-09-25 \
    --dry-run \
    --json-output data/historical-evidence/hilega-directional-option-recovery-2026-09-25-v1.json

This patch does NOT modify step-audit.jsonl, does NOT place orders, and does NOT restart workers.
