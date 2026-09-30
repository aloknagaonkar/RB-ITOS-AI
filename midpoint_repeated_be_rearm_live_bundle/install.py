#!/usr/bin/env python3
"""Install and gate repeated B/E rearm observation-only live shadow."""

from __future__ import annotations

import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path


BUNDLE = Path(__file__).resolve().parent
ROOT = BUNDLE.parent
FILES = (
    Path("backend/market_lab/midpoint_strategy/config.py"),
    Path("backend/market_lab/midpoint_strategy/workspace_contract.py"),
    Path("backend/market_lab/midpoint_strategy/live_shadow_v1.py"),
    Path("backend/market_lab/midpoint_strategy/live_shadow_ui.py"),
    Path("backend/market_lab/midpoint_strategy/option_observation.py"),
    Path("backend/market_lab/midpoint_strategy/materialize_option_observation.py"),
    Path("backend/market_lab/midpoint_strategy/degraded_exit_candidate.py"),
    Path("tests/test_midpoint_repeated_be_rearm_live_shadow.py"),
    Path("scripts/research_normal_b_tier1_classifier_exit.py"),
    Path("docs/MIDPOINT_INITIAL_RISK_RESEARCH_CHECKLIST.md"),
)


def set_env(path: Path, key: str, value: str) -> None:
    lines = path.read_text().splitlines() if path.exists() else []
    replacement = f"{key}={value}"
    output = []
    found = False
    for line in lines:
        if line.startswith(key + "="):
            output.append(replacement)
            found = True
        else:
            output.append(line)
    if not found:
        output.append(replacement)
    path.write_text("\n".join(output) + "\n")


def main() -> int:
    if not (ROOT / "pyproject.toml").exists():
        raise SystemExit(f"STOP: place bundle directly inside repository: {ROOT}")
    branch = subprocess.run(
        ["git", "branch", "--show-current"], cwd=ROOT, check=True,
        text=True, capture_output=True,
    ).stdout.strip()
    if branch != "feature/pcr-foundation":
        raise SystemExit(f"STOP: expected feature/pcr-foundation, found {branch!r}")
    python = ROOT / ".venv/bin/python"
    if not python.exists():
        raise SystemExit(f"STOP: virtualenv Python missing: {python}")
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup_root = ROOT / "data/backups" / f"midpoint-be-rearm-live-{stamp}"
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

    env = ROOT / ".env"
    if env.exists():
        backup = backup_root / ".env"
        backup.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(env, backup)
    set_env(env, "MIDPOINT_FAMILY_C_SHADOW_ENABLED", "false")
    set_env(env, "MIDPOINT_BE_REARM_SHADOW_ENABLED", "true")

    subprocess.run(
        [
            python, "-m", "pytest", "-q",
            "tests/test_midpoint_repeated_be_rearm_live_shadow.py",
            "tests/test_midpoint_c_pm_e_live_shadow.py",
            "tests/test_midpoint_normal_b_proved_live_shadow.py",
            "tests/test_midpoint_m3b_live_shadow_v1.py",
        ],
        cwd=ROOT,
        check=True,
    )
    subprocess.run(["git", "diff", "--check"], cwd=ROOT, check=True)
    print("PASS: repeated B/E rearm live-shadow source installed and tested.")
    print("Gates: C=false, BE_REARM=true.")
    print("Safety: observation=true, execution=false, paper=false, quantity=None.")
    print("API and workers were not restarted.")
    print(f"Backup: {backup_root}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
