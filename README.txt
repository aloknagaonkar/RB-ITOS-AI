B FAMILY 60-SESSION HEALTH VALIDATION V1

Tests the current post-entry B health hypothesis across the existing 60-session B sample.

Run:
cd ~/RB-ITOS-AI
source .venv/bin/activate
export PYTHONPATH=backend

python scripts/b_family_60_session_health_validation_v1.py | tee /tmp/b-family-60-session-health-validation-v1.txt

This does not change the frozen B entry definition or runtime/execution.
