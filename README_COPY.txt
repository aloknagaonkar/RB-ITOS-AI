Copy these files into the root of your RB-ITOS-AI repository preserving folders:

scripts/analyze_oi_event_boundary_v1.py
tests/test_analyze_oi_event_boundary_v1.py
oi_event_boundary_v1.patch

Then run:
source .venv/bin/activate
python -m pytest tests/test_analyze_oi_event_boundary_v1.py -v
