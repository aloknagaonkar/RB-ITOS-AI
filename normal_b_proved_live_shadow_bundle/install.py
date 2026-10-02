#!/usr/bin/env python3
"""Install and validate the observation-only NORMAL_B_PROVED live shadow."""

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
    "backend/market_lab/midpoint_strategy/live_shadow_ui.py",
    "backend/market_lab/midpoint_strategy/live_shadow_v1.py",
    "backend/market_lab/midpoint_strategy/normal_b_proved_candidate.py",
    "backend/market_lab/midpoint_strategy/workspace_contract.py",
    "frontend/src/midpointStrategyShadow.tsx",
    "tests/test_midpoint_normal_b_proved_live_shadow.py",
    "tests/test_normal_b_proved_candidate.py",
)
TESTS = (
    "tests/test_normal_b_proved_candidate.py",
    "tests/test_midpoint_normal_b_proved_live_shadow.py",
    "tests/test_midpoint_m3_live_shadow_ui.py",
    "tests/test_midpoint_m3b_live_shadow_v1.py",
    "tests/test_midpoint_v57_1_terminal_candle_parity.py",
    "tests/test_storage_api.py",
)


def run(command: list[str], *, cwd: Path = ROOT) -> None:
    print("Running:", " ".join(command), flush=True)
    subprocess.run(command, cwd=cwd, check=True)


def restore(backup: Path, existed: dict[str, bool]) -> None:
    print("Validation failed; restoring source files...", flush=True)
    for relative in TARGETS:
        target = ROOT / relative
        saved = backup / relative
        if existed[relative]:
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(saved, target)
        elif target.exists():
            target.unlink()


def main() -> int:
    if not (ROOT / "pyproject.toml").exists():
        raise SystemExit(f"STOP: bundle must be inside the repository root: {ROOT}")
    branch = subprocess.run(
        ["git", "branch", "--show-current"], cwd=ROOT, check=True,
        text=True, capture_output=True,
    ).stdout.strip()
    if branch != "feature/pcr-foundation":
        raise SystemExit(
            f"STOP: expected branch feature/pcr-foundation, found {branch!r}"
        )

    python = ROOT / ".venv/bin/python"
    if not python.exists():
        raise SystemExit(f"STOP: virtualenv Python not found: {python}")
    for relative in TARGETS:
        if not (PAYLOAD / relative).is_file():
            raise SystemExit(f"STOP: payload file missing: {relative}")

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup = ROOT / "data/backups" / f"normal-b-proved-live-{stamp}"
    existed: dict[str, bool] = {}
    for relative in TARGETS:
        source = ROOT / relative
        existed[relative] = source.is_file()
        if source.is_file():
            saved = backup / relative
            saved.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, saved)
    backup.mkdir(parents=True, exist_ok=True)
    (backup / "manifest.json").write_text(
        json.dumps({"branch": branch, "files_existed": existed}, indent=2) + "\n"
    )

    try:
        for relative in TARGETS:
            target = ROOT / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(PAYLOAD / relative, target)

        run([str(python), "-m", "pytest", "-q", *TESTS])
        run(["npm", "run", "build"], cwd=ROOT / "frontend")
        run(["git", "diff", "--check"])
    except (subprocess.CalledProcessError, OSError) as error:
        restore(backup, existed)
        print(f"STOP: validation failed ({error}); API and workers untouched")
        return 1

    print("PASS: NORMAL_B_PROVED observation-only live shadow installed and validated.")
    print("Safety: execution=false, paper=false, quantity=None, order_sent=false.")
    print("Baseline B/E lifecycle remains authoritative; candidate cannot close it.")
    print("API and workers were not restarted.")
    print(f"Backup: {backup}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
