#!/usr/bin/env python3
"""Install and validate same-page Hilega historical replay."""

from __future__ import annotations

import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path


BUNDLE = Path(__file__).resolve().parent
ROOT = BUNDLE.parent
FILES = (
    Path("backend/market_lab/hilega_historical_ui_api_v1.py"),
    Path("backend/market_lab/hilega_directional_candle_ui_v1.py"),
    Path("backend/market_lab/hilega_directional_historical_ui_v1.py"),
    Path("frontend/src/hilegaMilegaShadow.tsx"),
    Path("frontend/src/hilegaHistoricalReplay.tsx"),
    Path("docs/HILEGA_DIRECTIONAL_STRATEGY_VALIDATION.md"),
    Path("tests/test_hilega_live_session_visibility_v1.py"),
    Path("tests/test_hilega_directional_candle_ui_v1.py"),
    Path("tests/test_hilega_directional_historical_ui_v2.py"),
    Path("tests/test_hilega_same_page_historical_replay.py"),
)


def run(command: list[str], *, cwd: Path = ROOT) -> None:
    print("Running:", " ".join(command), flush=True)
    subprocess.run(command, cwd=cwd, check=True)


def main() -> int:
    if not (ROOT / "pyproject.toml").is_file():
        raise SystemExit(f"STOP: place bundle directly inside repository: {ROOT}")
    python = ROOT / ".venv/bin/python"
    if not python.is_file():
        raise SystemExit(f"STOP: virtualenv Python missing: {python}")

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup_root = ROOT / "data/backups" / f"hilega-same-page-history-{stamp}"
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
            "tests/test_hilega_live_session_visibility_v1.py",
            "tests/test_hilega_historical_ui_api_v1.py",
            "tests/test_hilega_session_replay_api_v1.py",
            "tests/test_hilega_directional_candle_ui_v1.py",
            "tests/test_hilega_directional_historical_ui_v2.py",
            "tests/test_hilega_directional_trade_dashboard_v1.py",
            "tests/test_hilega_same_page_historical_replay.py",
        ])
        run([
            str(python), "-m", "py_compile",
            "backend/market_lab/hilega_historical_ui_api_v1.py",
            "backend/market_lab/hilega_directional_candle_ui_v1.py",
            "backend/market_lab/hilega_directional_historical_ui_v1.py",
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
        print("STOP: validation failed; installed source restored.", file=sys.stderr)
        raise

    print("PASS: Hilega same-page historical replay installed and validated.")
    print("Completed directional live sessions become historical automatically.")
    print("Safety unchanged: observation=true, execution=false, paper=false, quantity=None.")
    print("API and workers were not restarted; restart is required.")
    if backup_root.exists():
        print("Backup:", backup_root)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
