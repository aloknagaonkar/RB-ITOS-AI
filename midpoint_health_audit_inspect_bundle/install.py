#!/usr/bin/env python3
"""Install and validate Midpoint Trade Health evidence in Audit Inspect."""

from __future__ import annotations

import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
BUNDLE = Path(__file__).resolve().parent / "files"
BUNDLE_VERSION = "V2_HEALTH_COLUMN_MATCHED"
FILES = (
    Path("backend/market_lab/midpoint_strategy/entry_health_live_v1.py"),
    Path("backend/market_lab/midpoint_strategy/live_shadow_v1.py"),
    Path("backend/market_lab/midpoint_strategy/live_shadow_ui.py"),
    Path("frontend/src/midpointStrategyShadow.tsx"),
    Path("frontend/src/midpointStrategyShadow.css"),
    Path("tests/test_midpoint_health_audit_inspect.py"),
)


def run(command: list[str], *, cwd: Path = ROOT) -> None:
    print("Running:", " ".join(command), flush=True)
    subprocess.run(command, cwd=cwd, check=True)


def main() -> int:
    print("Bundle:", BUNDLE_VERSION, flush=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup = ROOT / "data" / "backups" / f"midpoint-health-audit-{stamp}"
    copied: list[Path] = []
    try:
        for relative in FILES:
            source = BUNDLE / relative
            target = ROOT / relative
            if not source.exists():
                raise FileNotFoundError(source)
            if target.exists():
                saved = backup / relative
                saved.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(target, saved)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
            copied.append(relative)

        python = ROOT / ".venv" / "bin" / "python"
        python_command = str(python if python.exists() else Path(sys.executable))
        run(
            [
                python_command,
                "-m",
                "pytest",
                "-q",
                "tests/test_midpoint_health_audit_inspect.py",
                "tests/test_midpoint_t5_live_shadow_candidates.py",
                "tests/test_midpoint_m3_live_shadow_ui.py",
                "tests/test_midpoint_m3b_live_shadow_v1.py",
            ]
        )
        run(
            [
                python_command,
                "-m",
                "py_compile",
                "backend/market_lab/midpoint_strategy/entry_health_live_v1.py",
                "backend/market_lab/midpoint_strategy/live_shadow_v1.py",
                "backend/market_lab/midpoint_strategy/live_shadow_ui.py",
            ]
        )
        run(["npm", "run", "build"], cwd=ROOT / "frontend")
        run(["git", "diff", "--check"])
    except Exception:
        for relative in reversed(copied):
            target = ROOT / relative
            saved = backup / relative
            if saved.exists():
                shutil.copy2(saved, target)
            elif target.exists():
                target.unlink()
        print("STOP: validation failed; installed files restored.", file=sys.stderr)
        raise

    print("PASS: Midpoint Trade Health evidence added to Audit Inspect.")
    print("Layout: combined columns plus event-level Health status and support count.")
    print("Safety: observation only; no veto, baseline exit, order or quantity changed.")
    print("API and workers were not restarted.")
    if backup.exists():
        print("Backup:", backup)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
