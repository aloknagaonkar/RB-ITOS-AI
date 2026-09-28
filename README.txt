MIDPOINT M2.1 — AUDIT PATH RUNTIME FIX

Cause:
M2 defined `_all_rows(path: Path = AUDIT_PATH)`.
Python evaluates default arguments at function-definition time, so tests that
monkeypatch `ui.AUDIT_PATH` still read the original live audit file.

Fix:
Use `_all_rows(path: Path | None = None)` and resolve `AUDIT_PATH` inside the
function at call time.

Run:
cd ~/RB-ITOS-AI
source .venv/bin/activate
export PYTHONPATH=backend

python scripts/apply_midpoint_m2_1_audit_path_runtime_fix.py

python -m pytest   tests/test_midpoint_m3_1_query_defaults.py   tests/test_midpoint_m3_live_shadow_ui.py   tests/test_midpoint_m2_live_replay_ui.py -v

python -m pytest tests -q -k 'midpoint' --disable-warnings
