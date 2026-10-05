from __future__ import annotations

import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
BUNDLE = Path(__file__).resolve().parent / "files"
BACKUP = ROOT / "data" / "backups" / (
    "hilega-upstox-sandbox-execution-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
)

FILES = [
    Path("backend/market_lab/hilega_upstox_sandbox_execution_v1.py"),
    Path("tests/test_hilega_upstox_sandbox_execution_v1.py"),
    Path("docs/paper/HILEGA_UPSTOX_SANDBOX_EXECUTION_V1.md"),
]


def run(command: list[str]) -> None:
    print("Running:", " ".join(command))
    subprocess.run(command, cwd=ROOT, check=True)


def main() -> int:
    python = ROOT / ".venv" / "bin" / "python"
    if not python.exists():
        raise SystemExit("STOP: activate/create the repository .venv first")

    installed: list[Path] = []
    try:
        for relative in FILES:
            source = BUNDLE / relative
            target = ROOT / relative
            if target.exists():
                backup = BACKUP / relative
                backup.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(target, backup)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
            installed.append(relative)

        run([str(python), "-m", "pytest", "-q", "tests/test_hilega_upstox_sandbox_execution_v1.py"])
        run([str(python), "-m", "py_compile", "backend/market_lab/hilega_upstox_sandbox_execution_v1.py"])
        run(["git", "diff", "--check"])
    except Exception as exc:
        for relative in installed:
            backup = BACKUP / relative
            target = ROOT / relative
            if backup.exists():
                shutil.copy2(backup, target)
            elif target.exists():
                target.unlink()
        raise SystemExit(f"STOP: validation failed; installed files restored: {exc}") from exc

    print("PASS: Hilega Upstox Sandbox execution foundation installed and validated.")
    print("Sandbox gate remains disabled; kill switch remains active by default.")
    print("Live Hilega strategy, worker, audit, orders and quantity were untouched.")
    if BACKUP.exists():
        print("Backup:", BACKUP)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
