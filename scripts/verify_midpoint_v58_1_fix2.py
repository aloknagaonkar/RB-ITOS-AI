#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
from pathlib import Path

V58 = Path("scripts/midpoint_v58_480_session_be_accounting_validation.py")

spec = importlib.util.spec_from_file_location("v58_fix2_verify", V58)
if spec is None or spec.loader is None:
    raise SystemExit("STOP: cannot load V58")
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)

assert hasattr(m, "V57"), "V57 constant missing"
assert Path(m.V57).name == "midpoint_v57_full_historical_be_lifecycle_replay.py"
print("PASS: V58 has V57 replay source configured.")

src = V58.read_text()
assert 'v57.replay_session(' in src
print("PASS: V58 replay_session delegates to V57.")
