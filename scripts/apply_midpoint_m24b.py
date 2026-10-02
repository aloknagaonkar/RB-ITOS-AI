#!/usr/bin/env python3
from pathlib import Path
import shutil, sys

repo = Path.cwd()
target_tsx = repo / "frontend/src/midpointStrategyShadow.tsx"
target_css = repo / "frontend/src/midpointStrategyShadow.css"
src_dir = Path(__file__).resolve().parent

for target in (target_tsx, target_css):
    if not target.exists():
        raise SystemExit(f"STOP: missing target {target}")

for target in (target_tsx, target_css):
    backup = target.with_name(target.name + ".pre-m2-4b.bak")
    if not backup.exists():
        shutil.copy2(target, backup)
        print("BACKUP:", backup)

shutil.copy2(src_dir / "midpointStrategyShadow.tsx", target_tsx)
shutil.copy2(src_dir / "midpointStrategyShadow.css", target_css)

print("INSTALLED:", target_tsx)
print("INSTALLED:", target_css)
