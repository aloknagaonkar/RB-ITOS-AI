from __future__ import annotations

import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BUNDLE = Path(__file__).resolve().parent
FILES = (
    Path("backend/market_lab/hilega_upstox_broker_preflight_v1.py"),
    Path("tests/test_hilega_upstox_broker_preflight_v1.py"),
    Path("docs/strategies/HILEGA_UPSTOX_BROKER_PREFLIGHT_V1.md"),
)


def run(command: list[str]) -> None:
    print("Running:", " ".join(command))
    subprocess.run(command, cwd=ROOT, check=True)


def main() -> int:
    python = Path(sys.executable)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup = ROOT / "data" / "backups" / f"hilega-upstox-preflight-{stamp}"
    installed: list[tuple[Path, Path | None]] = []

    try:
        for relative in FILES:
            source = BUNDLE / "files" / relative
            target = ROOT / relative
            if not source.is_file():
                raise FileNotFoundError(f"bundle source missing: {source}")
            saved = None
            if target.exists():
                saved = backup / relative
                saved.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(target, saved)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
            installed.append((target, saved))

        run([str(python), "-m", "pytest", "-q", "tests/test_hilega_upstox_broker_preflight_v1.py"])
        run([str(python), "-m", "py_compile", "backend/market_lab/hilega_upstox_broker_preflight_v1.py"])
        run(["git", "diff", "--check"])
    except Exception as exc:
        for target, saved in reversed(installed):
            if saved is None:
                target.unlink(missing_ok=True)
            else:
                shutil.copy2(saved, target)
        print(f"STOP: validation failed; installed source restored: {exc}")
        return 1

    print("PASS: Hilega Upstox broker preflight installed and validated.")
    print("Live profile checks are read-only; order commands use Sandbox only.")
    print("No paper gate, Hilega rule, exit, service, quantity or live order was changed.")
    if backup.exists():
        print("Backup:", backup)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
