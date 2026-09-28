MIDPOINT V58.1 FIX3 — EXACT CURRENT V58 SCRIPT PATCH

This patch matches the current script exactly:
- load helper: load_module(...)
- replay function: replay(day,u,fut)
- single-quoted path constants

Run:

cd ~/RB-ITOS-AI
source .venv/bin/activate
export PYTHONPATH=backend

python scripts/apply_midpoint_v58_1_fix3_exact_current_script.py
python scripts/verify_midpoint_v58_1_fix3.py

python -m pytest tests/test_midpoint_v58_accounting_contract.py -v

python scripts/midpoint_v58_480_session_be_accounting_validation.py

cat \
data/historical-evidence/hilega-pcr-oi-support-research-v1/\
midpoint-v58-480-session-be-accounting/summary-v58.txt

No restart required.
