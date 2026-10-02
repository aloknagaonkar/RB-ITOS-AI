#!/usr/bin/env python3
from pathlib import Path
import shutil

ROOT = Path(__file__).resolve().parents[1]

FILES = {
    ROOT / "patches/backend/live_shadow_ui.py":
        Path("backend/market_lab/midpoint_strategy/live_shadow_ui.py"),
    ROOT / "patches/backend/midpoint_m2_materialize_historical_replay.py":
        Path("scripts/midpoint_m2_materialize_historical_replay.py"),
    ROOT / "patches/frontend/midpointStrategyShadow.tsx":
        Path("frontend/src/midpointStrategyShadow.tsx"),
    ROOT / "patches/frontend/midpointStrategyShadow.css":
        Path("frontend/src/midpointStrategyShadow.css"),
}

for src, dst in FILES.items():
    if not src.exists():
        raise SystemExit(f"SAFE STOP: missing package payload {src}")
    if not dst.exists():
        raise SystemExit(f"SAFE STOP: target missing {dst}")
    backup = dst.with_name(dst.name + ".pre-m2-2.bak")
    if not backup.exists():
        shutil.copy2(dst, backup)
    shutil.copy2(src, dst)
    print(f"Patched: {dst}")

print("PASS: M2.2 full-day date-wise replay UI applied.")
print("Strategy semantics and execution controls were not modified.")
