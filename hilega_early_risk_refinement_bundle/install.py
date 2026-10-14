#!/usr/bin/env python3
"""Install Hilega V2 flat-wait, hard-T+10 early-risk research."""

from __future__ import annotations

import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path


BUNDLE = Path(__file__).resolve().parent
ROOT = BUNDLE.parent
FILES = (
    Path("scripts/research_hilega_early_risk_refinement.py"),
    Path("tests/test_research_hilega_early_risk_refinement.py"),
)


def run(command: list[str]) -> None:
    print("Running:", " ".join(command), flush=True)
    subprocess.run(command, cwd=ROOT, check=True)


def main() -> int:
    if not (ROOT / "pyproject.toml").is_file():
        raise SystemExit(f"STOP: place bundle directly inside repository: {ROOT}")
    python = ROOT / ".venv/bin/python"
    if not python.is_file():
        raise SystemExit(f"STOP: virtualenv Python missing: {python}")

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup_root = ROOT / "data/backups" / f"hilega-early-risk-{stamp}"
    installed: list[Path] = []
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
            installed.append(relative)

        run([
            str(python), "-m", "pytest", "-q",
            "tests/test_research_hilega_early_risk_refinement.py",
            "tests/test_research_hilega_t5_failure_exits.py",
            "tests/test_research_hilega_wma_positive_direction.py",
            "tests/test_research_hilega_alignment_points_490.py",
        ])
        run([
            str(python), "-m", "py_compile",
            "scripts/research_hilega_early_risk_refinement.py",
        ])
        run(["git", "diff", "--check"])
    except Exception:
        for relative in reversed(installed):
            target = ROOT / relative
            backup = backup_root / relative
            if backup.exists():
                shutil.copy2(backup, target)
            elif target.exists():
                target.unlink()
        print("STOP: validation failed; installed source restored.", file=sys.stderr)
        raise

    print("PASS: installed Hilega V2 flat-wait hard-T+10 research.")
    print("WMA FLAT_WAIT is neutral; it cannot by itself reject or exit.")
    print("Candidates A/B/C are research-only; canonical lifecycle unchanged.")
    print("No live strategy, service, audit, order, paper order or quantity changed.")
    if backup_root.exists():
        print("Backup:", backup_root)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
