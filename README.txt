B FAMILY — 180-SESSION DATA HEALTH AUDIT V14.1
==================================================

This fixes V14's incorrect assumption of one combined framework JSON.

V14.1 imports the canonical Family-B validator and directly reuses:
- FRAMEWORK_FILES
- load_framework()
- load_underlying()
- FUTURES_CSV
- is_trusted()
- family_b_for_event()

Expected PASS parity:
- framework sessions = 180
- underlying sessions = 180
- futures/VWAP sessions = 180
- duplicate conflicts = 0
- B total = 45
- B older = 27
- B latest60 = 18

Run:
cd ~/RB-ITOS-AI
source .venv/bin/activate
export PYTHONPATH=backend

python scripts/b_family_180_data_health_audit_v14_1.py \
  | tee /tmp/b-family-180-data-health-v14-1.txt
