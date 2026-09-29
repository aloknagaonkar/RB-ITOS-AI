#!/usr/bin/env python3
from pathlib import Path
import subprocess

repo = Path.cwd()
tsx = repo / "frontend/src/midpointStrategyShadow.tsx"
css = repo / "frontend/src/midpointStrategyShadow.css"

for p in (tsx, css):
    if not p.exists():
        raise SystemExit(f"STOP: missing {p}")

required = [
    "STRUCTURE QUALIFICATION",
    "STRATEGY / OWNERSHIP QUALIFICATION",
    "MANAGEMENT QUALIFICATION",
    "CONTINUE ·",
    "FORWARD OOS REPLAY · NO-REENTRY BASELINE",
    "Exact contract not selected",
]
text = tsx.read_text()
for token in required:
    if token not in text:
        raise SystemExit(f"STOP: missing frontend token: {token}")

print("frontend markers: PASS")
subprocess.run(["npm", "run", "build"], cwd=repo / "frontend", check=True)
print("frontend build: PASS")
