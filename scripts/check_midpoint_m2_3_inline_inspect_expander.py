#!/usr/bin/env python3
from pathlib import Path

tsx = Path("frontend/src/midpointStrategyShadow.tsx").read_text()
css = Path("frontend/src/midpointStrategyShadow.css").read_text()

required = [
    "mp-inline-detail-row",
    "mp-inline-audit",
    "selected?.event_id===eventId",
    "Inspect expands directly below",
]
for token in required:
    if token not in tsx and token not in css:
        raise SystemExit(f"FAIL: expected M2.3 token missing: {token}")

for forbidden in ["function AuditDrawer(", "mp-drawer-backdrop", "mp-audit-drawer"]:
    if forbidden in tsx or forbidden in css:
        raise SystemExit(f"FAIL: obsolete drawer token remains: {forbidden}")

print("PASS: M2.3 inline Inspect source checks.")
