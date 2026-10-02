#!/usr/bin/env python3
import json
import subprocess
from pathlib import Path

print("== compile ==")
subprocess.run(
    ["python", "-m", "py_compile",
     "backend/market_lab/midpoint_strategy/live_shadow_ui.py"],
    check=True,
)
print("backend syntax: PASS")

print("\n== tests ==")
subprocess.run(
    ["python", "-m", "pytest", "tests",
     "-k", "midpoint and (ui or historical or replay)", "-q"],
    check=True,
)

root = Path(
    "data/historical-evidence/hilega-pcr-oi-support-research-v1/"
    "midpoint-ui-replay-v1"
)
manifest = json.loads((root / "manifest.json").read_text())
print("\nmanifest sessions:", manifest.get("session_count"))
print("M2.4A local verification complete.")
