#!/usr/bin/env python3
from pathlib import Path
import subprocess

tsx=Path("frontend/src/midpointStrategyShadow.tsx")
css=Path("frontend/src/midpointStrategyShadow.css")

required=[
    "function ActiveTradeSection",
    "function ExitDetailsSection",
    "mp-summary-compact",
    "mp-lifecycle-compact",
    "<ActiveTradeSection status={status}/>",
    "<ExitDetailsSection status={status}/>",
]
text=tsx.read_text()
for token in required:
    if token not in text:
        raise SystemExit(f"STOP: missing token: {token}")

ct=css.read_text()
for token in [".mp-summary-compact",".mp-lifecycle-compact",".mp-trade-strip",".mp-exit-strip"]:
    if token not in ct:
        raise SystemExit(f"STOP: missing CSS token: {token}")

print("M2.5 layout markers: PASS")
subprocess.run(["npm","run","build"],cwd="frontend",check=True)
print("frontend build: PASS")
