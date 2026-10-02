#!/usr/bin/env python3
from pathlib import Path
import subprocess

tsx = Path("frontend/src/midpointStrategyShadow.tsx")
css = Path("frontend/src/midpointStrategyShadow.css")

required = [
    "function livePresentationFromStatus",
    "function LiveContinuationPanel",
    "CONTINUE · ${direction}_ACTIVE",
    "<LiveContinuationPanel status={status}/>",
    "Presentation-only projection from immutable live Midpoint audit state",
]
text = tsx.read_text()
for token in required:
    if token not in text:
        raise SystemExit(f"STOP: missing token: {token}")

if ".mp-live-continuation-panel" not in css.read_text():
    raise SystemExit("STOP: live continuation CSS missing")

print("M2.4C frontend markers: PASS")
subprocess.run(["npm", "run", "build"], cwd="frontend", check=True)
print("frontend build: PASS")
