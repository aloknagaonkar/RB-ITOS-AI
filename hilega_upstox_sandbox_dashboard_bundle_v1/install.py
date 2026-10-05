from __future__ import annotations

import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BUNDLE = Path(__file__).resolve().parent
FILES = BUNDLE / "files"
STAMP = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
BACKUP = ROOT / "data" / "backups" / f"hilega-upstox-sandbox-dashboard-{STAMP}"

COPIES = [
    "backend/market_lab/hilega_upstox_sandbox_dashboard_v1.py",
    "backend/market_lab/hilega_upstox_sandbox_execution_v1.py",
    "backend/market_lab/hilega_upstox_sandbox_live_worker_v1.py",
    "frontend/src/hilegaUpstoxSandboxDashboard.tsx",
    "tests/test_hilega_upstox_sandbox_dashboard_v1.py",
]


def patch_once(path: Path, marker: str, anchor: str, replacement: str) -> None:
    text = path.read_text()
    if marker in text:
        return
    if anchor not in text:
        raise RuntimeError(f"required patch anchor unavailable: {path}: {anchor}")
    path.write_text(text.replace(anchor, replacement, 1))


def backup(path: Path) -> None:
    if path.exists():
        target = BACKUP / path.relative_to(ROOT)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, target)


def restore(touched: list[Path]) -> None:
    for path in reversed(touched):
        saved = BACKUP / path.relative_to(ROOT)
        if saved.exists():
            path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(saved, path)
        elif path.exists():
            path.unlink()


def run(command: list[str]) -> None:
    print("Running:", " ".join(command))
    subprocess.run(command, cwd=ROOT, check=True)


def main() -> int:
    touched = [ROOT / item for item in COPIES] + [
        ROOT / "backend/market_lab/api.py",
        ROOT / "frontend/src/hilegaMilegaShadow.tsx",
    ]
    for path in touched:
        backup(path)
    try:
        for item in COPIES:
            source, target = FILES / item, ROOT / item
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)

        api = ROOT / "backend/market_lab/api.py"
        patch_once(
            api,
            "hilega_upstox_sandbox_dashboard_router",
            "from .hilega_directional_live_shadow_ui_v1 import router as hilega_directional_live_shadow_router\n",
            "from .hilega_directional_live_shadow_ui_v1 import router as hilega_directional_live_shadow_router\n"
            "from .hilega_upstox_sandbox_dashboard_v1 import router as hilega_upstox_sandbox_dashboard_router\n",
        )
        patch_once(
            api,
            "app.include_router(hilega_upstox_sandbox_dashboard_router)",
            "    app.include_router(hilega_directional_live_shadow_router)\n",
            "    app.include_router(hilega_directional_live_shadow_router)\n"
            "    app.include_router(hilega_upstox_sandbox_dashboard_router)\n",
        )

        ui = ROOT / "frontend/src/hilegaMilegaShadow.tsx"
        patch_once(
            ui,
            "HilegaUpstoxSandboxDashboard from",
            "import HilegaHistoricalReplay from './hilegaHistoricalReplay'\n",
            "import HilegaHistoricalReplay from './hilegaHistoricalReplay'\n"
            "import HilegaUpstoxSandboxDashboard from './hilegaUpstoxSandboxDashboard'\n"
            "import './liveShadow.css'\n",
        )
        patch_once(
            ui,
            "<HilegaUpstoxSandboxDashboard/>",
            "    {error&&<div className=\"banner error\">{error}</div>}\n",
            "    {error&&<div className=\"banner error\">{error}</div>}\n\n"
            "    <HilegaUpstoxSandboxDashboard/>\n",
        )

        python = str(ROOT / ".venv/bin/python")
        run([python, "-m", "pytest", "-q",
             "tests/test_hilega_upstox_sandbox_dashboard_v1.py",
             "tests/test_hilega_upstox_sandbox_live_worker_v1.py",
             "tests/test_hilega_sandbox_event_bridge_v1.py",
             "tests/test_hilega_upstox_sandbox_execution_v1.py"])
        run([python, "-m", "py_compile",
             "backend/market_lab/hilega_upstox_sandbox_dashboard_v1.py",
             "backend/market_lab/hilega_upstox_sandbox_execution_v1.py",
             "backend/market_lab/hilega_upstox_sandbox_live_worker_v1.py"])
        run(["npm", "--prefix", "frontend", "run", "build"])
        run(["git", "diff", "--check"])
    except Exception as exc:
        restore(touched)
        print(f"STOP: validation failed; installed source restored: {exc}")
        return 1
    print("PASS: Hilega Upstox Sandbox dashboard installed and validated.")
    print("Restart is required. Strategy rules and live execution are unchanged.")
    print("Backup:", BACKUP)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
