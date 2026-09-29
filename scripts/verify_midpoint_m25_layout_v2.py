#!/usr/bin/env python3
from pathlib import Path
import subprocess

tsx=Path("frontend/src/midpointStrategyShadow.tsx")
css=Path("frontend/src/midpointStrategyShadow.css")
text=tsx.read_text()
for token in [
 "function ActiveTradeSection",
 "function ExitDetailsSection",
 "mp-summary-compact",
 "mp-lifecycle-compact",
 "<ActiveTradeSection status={status}/>",
 "<ExitDetailsSection status={status}/>",
]:
    if token not in text:
        raise SystemExit(f"STOP: missing token: {token}")
for token in [".mp-summary-compact",".mp-lifecycle-compact",".mp-trade-strip",".mp-exit-strip"]:
    if token not in css.read_text():
        raise SystemExit(f"STOP: missing CSS token: {token}")
print("M2.5 layout v2 markers: PASS")
subprocess.run(["npm","run","build"],cwd="frontend",check=True)
print("frontend build: PASS")
