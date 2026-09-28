#!/usr/bin/env python3
from pathlib import Path

p = Path("backend/market_lab/midpoint_strategy/live_shadow_v1.py")
s = p.read_text()

checks = {
    "collector import": "MidpointV621ForwardOOSCollector" in s,
    "env gate": 'MIDPOINT_V62_OOS_COLLECTOR_ENABLED' in s,
    "audit tail helper": "def _v621_read_new_audit_events" in s,
    "completed minute helper": "def _v621_observe_completed_minute" in s,
    "process hook": "self._v621_observe_completed_minute(" in s.split("def process(",1)[-1],
    "terminal ordering": 'event.get("event_type") == "STRUCTURAL_TERMINAL"' in s,
}
for name, ok in checks.items():
    print(f"{name}: {'PASS' if ok else 'FAIL'}")
assert all(checks.values())
print("PASS: V62.2 source verification complete.")
