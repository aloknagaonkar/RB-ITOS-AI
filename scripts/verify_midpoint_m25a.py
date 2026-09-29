#!/usr/bin/env python3
from pathlib import Path
import subprocess

tsx=Path("frontend/src/midpointStrategyShadow.tsx")
css=Path("frontend/src/midpointStrategyShadow.css")
required=[
 "function MidpointFreshnessHeader",
 "function CheckpointComparison",
 "function MinuteExplainPanel",
 "Explain minute",
 "LATEST MIDPOINT DETAILS",
 "WHAT MUST HAPPEN NEXT",
 "Lifecycle checkpoint comparison",
 "setLastRefresh(new Date().toISOString())",
]
text=tsx.read_text()
for token in required:
    if token not in text:
        raise SystemExit(f"STOP: missing token: {token}")
if ".mp-freshness{" not in css.read_text():
    raise SystemExit("STOP: freshness CSS missing")
print("M2.5A markers: PASS")
subprocess.run(["npm","run","build"],cwd="frontend",check=True)
print("frontend build: PASS")
