#!/usr/bin/env python3
"""Install corrected PM midpoint-first B/E observation-only rules."""

from __future__ import annotations

import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path


BUNDLE = Path(__file__).resolve().parent
ROOT = BUNDLE.parent
FILES = (
    Path("backend/market_lab/midpoint_strategy/models.py"),
    Path("backend/market_lab/midpoint_strategy/extended_entry_candidates.py"),
    Path("backend/market_lab/midpoint_strategy/runtime.py"),
    Path("backend/market_lab/midpoint_strategy/live_shadow_v1.py"),
    Path("backend/market_lab/midpoint_strategy/live_shadow_ui.py"),
    Path("backend/market_lab/midpoint_strategy/option_observation.py"),
    Path("backend/market_lab/midpoint_strategy/materialize_option_observation.py"),
    Path("backend/market_lab/midpoint_strategy/degraded_exit_candidate.py"),
    Path("scripts/validate_midpoint_pm_e_session.py"),
    Path("scripts/validate_midpoint_live_session.py"),
    Path("scripts/midpoint_c_pm_e_shared_lifecycle_validation.py"),
    Path("tests/test_midpoint_extended_entry_candidates.py"),
    Path("tests/test_midpoint_c_pm_e_live_shadow.py"),
    Path("docs/MIDPOINT_CURRENT_RULEBOOK.md"),
    Path("docs/MIDPOINT_INITIAL_RISK_RESEARCH_CHECKLIST.md"),
)


def main() -> int:
    if not (ROOT / "pyproject.toml").exists():
        raise SystemExit(f"STOP: place bundle directly inside repository: {ROOT}")
    branch = subprocess.run(
        ["git", "branch", "--show-current"],
        cwd=ROOT,
        check=True,
        text=True,
        capture_output=True,
    ).stdout.strip()
    if branch != "feature/pcr-foundation":
        raise SystemExit(
            f"STOP: expected feature/pcr-foundation, found {branch!r}"
        )
    python = ROOT / ".venv/bin/python"
    if not python.exists():
        raise SystemExit(f"STOP: virtualenv Python missing: {python}")

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup_root = ROOT / "data/backups" / f"midpoint-pm-be-rules-{stamp}"
    for relative in FILES:
        source = BUNDLE / "files" / relative
        target = ROOT / relative
        if not source.is_file():
            raise SystemExit(f"STOP: payload missing: {source}")
        if target.exists():
            backup = backup_root / relative
            backup.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(target, backup)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)

    subprocess.run(
        [
            python,
            "-m",
            "pytest",
            "-q",
            "tests/test_midpoint_extended_entry_candidates.py",
            "tests/test_midpoint_c_pm_e_live_shadow.py",
            "tests/test_midpoint_repeated_be_rearm_live_shadow.py",
            "tests/test_midpoint_normal_b_proved_live_shadow.py",
            "tests/test_midpoint_m3b_live_shadow_v1.py",
            "tests/test_midpoint_m25b_option_observation.py",
        ],
        cwd=ROOT,
        check=True,
    )
    subprocess.run(["git", "diff", "--check"], cwd=ROOT, check=True)

    print("PASS: corrected PM midpoint-first B/E rules installed and tested.")
    print("PM: midpoint direction -> boundary -> canonical B/E owner.")
    print("PM_E immediate; PM_B delayed confirmation; cutoff 15:15.")
    print("PM live gate and .env were not changed. Services were not restarted.")
    print("Safety: observation=true, execution=false, paper=false, quantity=None.")
    print(f"Backup: {backup_root}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
