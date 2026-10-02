#!/usr/bin/env python3
"""Install minute-by-minute dual health inside the Midpoint audit table."""

from __future__ import annotations

import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path


BUNDLE = Path(__file__).resolve().parent
ROOT = BUNDLE.parent
FILES = (
    Path("backend/market_lab/midpoint_strategy/live_shadow_v1.py"),
    Path("backend/market_lab/midpoint_strategy/live_shadow_ui.py"),
    Path("frontend/src/midpointStrategyShadow.tsx"),
    Path("frontend/src/midpointStrategyShadow.css"),
    Path("tests/test_midpoint_continuous_system_health.py"),
    Path("tests/test_midpoint_active_rule_health_ui.py"),
)


def run(command: list[str], *, cwd: Path = ROOT) -> None:
    print("Running:", " ".join(command), flush=True)
    subprocess.run(command, cwd=cwd, check=True)


def main() -> int:
    if not (ROOT / "pyproject.toml").exists():
        raise SystemExit(f"STOP: place bundle directly inside repository: {ROOT}")
    python = ROOT / ".venv/bin/python"
    if not python.exists():
        raise SystemExit(f"STOP: virtualenv Python missing: {python}")

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup_root = ROOT / "data/backups" / f"midpoint-minute-health-audit-{stamp}"
    copied: list[Path] = []
    try:
        for relative in FILES:
            source = BUNDLE / "files" / relative
            target = ROOT / relative
            if not source.is_file():
                raise FileNotFoundError(source)
            if target.exists():
                backup = backup_root / relative
                backup.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(target, backup)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
            copied.append(relative)

        run([
            str(python), "-m", "pytest", "-q",
            "tests/test_midpoint_continuous_system_health.py",
            "tests/test_midpoint_active_rule_health_ui.py",
            "tests/test_midpoint_trade_lane_dashboard.py",
            "tests/test_midpoint_health_audit_inspect.py",
            "tests/test_midpoint_a_continuous_health_live.py",
            "tests/test_midpoint_t5_live_shadow_candidates.py",
            "tests/test_midpoint_repeated_be_rearm_live_shadow.py",
            "tests/test_midpoint_m3_live_shadow_ui.py",
            "tests/test_storage_api.py",
        ])
        run([
            str(python), "-m", "py_compile",
            "backend/market_lab/midpoint_strategy/live_shadow_v1.py",
            "backend/market_lab/midpoint_strategy/live_shadow_ui.py",
        ])
        run(["npm", "run", "build"], cwd=ROOT / "frontend")
        run(["git", "diff", "--check"])
    except Exception:
        for relative in reversed(copied):
            target = ROOT / relative
            backup = backup_root / relative
            if backup.exists():
                shutil.copy2(backup, target)
            elif target.exists():
                target.unlink()
        print("STOP: validation failed; source files restored.", file=sys.stderr)
        raise

    print("PASS: minute-by-minute health rows added to the existing Midpoint audit.")
    print("Existing panels, signal rows, columns and health presentation are unchanged.")
    print("Safety unchanged: observation=true, execution=false, paper=false, quantity=None.")
    print("API and workers were not restarted; restart is required.")
    if backup_root.exists():
        print("Backup:", backup_root)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
