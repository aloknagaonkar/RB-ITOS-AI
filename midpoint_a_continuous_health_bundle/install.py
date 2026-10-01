#!/usr/bin/env python3
"""Install A + continuous-health observation-only shadow candidates."""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path


BUNDLE = Path(__file__).resolve().parent
ROOT = BUNDLE.parent
PAYLOAD = BUNDLE / "files"
TARGETS = (
    "backend/market_lab/midpoint_strategy/config.py",
    "backend/market_lab/midpoint_strategy/models.py",
    "backend/market_lab/midpoint_strategy/runtime.py",
    "backend/market_lab/midpoint_strategy/live_shadow_v1.py",
    "backend/market_lab/midpoint_strategy/live_shadow_ui.py",
    "backend/market_lab/midpoint_strategy/workspace_contract.py",
    "backend/market_lab/midpoint_strategy/option_observation.py",
    "backend/market_lab/midpoint_strategy/materialize_option_observation.py",
    "backend/market_lab/midpoint_strategy/degraded_exit_candidate.py",
    "backend/market_lab/midpoint_strategy/continuous_health_exit_v1.py",
    "frontend/src/midpointStrategyShadow.tsx",
    "scripts/backtest_midpoint_a_continuous_health.py",
    "tests/test_midpoint_a_continuous_health_live.py",
    "docs/MIDPOINT_A_CONTINUOUS_HEALTH_CHECKLIST.md",
)
TESTS = (
    "tests/test_midpoint_a_continuous_health_live.py",
    "tests/test_midpoint_v55_boundary_classifier.py",
    "tests/test_midpoint_v56_live_e_wiring.py",
    "tests/test_midpoint_t5_live_shadow_candidates.py",
    "tests/test_midpoint_health_audit_inspect.py",
    "tests/test_midpoint_repeated_be_rearm_live_shadow.py",
    "tests/test_midpoint_c_pm_e_live_shadow.py",
    "tests/test_midpoint_m3_live_shadow_ui.py",
    "tests/test_midpoint_v57_1_terminal_candle_parity.py",
    "tests/test_storage_api.py",
)
FLAGS = {
    "MIDPOINT_FAMILY_A_SHADOW_ENABLED": "true",
    "MIDPOINT_CONTINUOUS_HEALTH_EXIT_CANDIDATE_ENABLED": "true",
}


def run(command: list[str], *, cwd: Path = ROOT) -> None:
    print("Running:", " ".join(command), flush=True)
    subprocess.run(command, cwd=cwd, check=True)


def restore(backup: Path, existed: dict[str, bool]) -> None:
    for relative in TARGETS:
        target, saved = ROOT / relative, backup / relative
        if existed[relative]:
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(saved, target)
        elif target.exists():
            target.unlink()


def enable_flags(env_path: Path) -> None:
    lines = env_path.read_text().splitlines() if env_path.exists() else []
    output: list[str] = []
    found: set[str] = set()
    for line in lines:
        key = line.split("=", 1)[0].strip() if "=" in line else ""
        if key in FLAGS:
            output.append(f"{key}={FLAGS[key]}")
            found.add(key)
        else:
            output.append(line)
    for key, value in FLAGS.items():
        if key not in found:
            output.append(f"{key}={value}")
    env_path.write_text("\n".join(output) + "\n")


def main() -> int:
    if not (ROOT / "pyproject.toml").exists():
        raise SystemExit(f"STOP: place this bundle in repository root: {ROOT}")
    branch = subprocess.run(
        ["git", "branch", "--show-current"], cwd=ROOT, check=True,
        text=True, capture_output=True,
    ).stdout.strip()
    if branch != "feature/pcr-foundation":
        raise SystemExit(
            f"STOP: expected feature/pcr-foundation, found {branch!r}"
        )
    python = ROOT / ".venv/bin/python"
    if not python.exists():
        raise SystemExit(f"STOP: virtualenv Python unavailable: {python}")
    for relative in TARGETS:
        if not (PAYLOAD / relative).is_file():
            raise SystemExit(f"STOP: bundle payload missing: {relative}")

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup = ROOT / "data/backups" / f"midpoint-a-health-{stamp}"
    existed: dict[str, bool] = {}
    for relative in TARGETS:
        source = ROOT / relative
        existed[relative] = source.is_file()
        if source.is_file():
            saved = backup / relative
            saved.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, saved)
    env_path = ROOT / ".env"
    if env_path.exists():
        backup.mkdir(parents=True, exist_ok=True)
        shutil.copy2(env_path, backup / ".env")
    backup.mkdir(parents=True, exist_ok=True)
    (backup / "manifest.json").write_text(json.dumps({
        "branch": branch, "files_existed": existed, "flags": FLAGS,
    }, indent=2) + "\n")

    try:
        for relative in TARGETS:
            target = ROOT / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(PAYLOAD / relative, target)
        run([str(python), "-m", "pytest", "-q", *TESTS])
        run([str(python), "-m", "py_compile",
             "scripts/backtest_midpoint_a_continuous_health.py"])
        run(["npm", "run", "build"], cwd=ROOT / "frontend")
        run(["git", "diff", "--check"])
    except (OSError, subprocess.CalledProcessError) as error:
        restore(backup, existed)
        print(f"STOP: validation failed ({error}); .env and services untouched")
        return 1

    enable_flags(env_path)
    print("PASS: Family A and continuous-health candidates installed.")
    print("Enabled gates: A=true, continuous-health=true.")
    print("A is parallel and non-blocking; CURRENT_EXIT_POLICY is unchanged.")
    print("Safety: observation=true, execution=false, paper=false, quantity=None.")
    print("API and workers were not restarted.")
    print("Backup:", backup)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
