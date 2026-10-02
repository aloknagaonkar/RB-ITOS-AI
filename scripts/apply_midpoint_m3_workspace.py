#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path
import shutil


ROOT = Path(__file__).resolve().parents[1]
API = ROOT / "backend/market_lab/api.py"
APP = ROOT / "frontend/src/App.tsx"


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise SystemExit(
            f"STOP: expected exactly one {label} anchor, found {count}. "
            "Repo changed; do not patch blindly."
        )
    return text.replace(old, new, 1)


def patch_api(text: str) -> str:
    if "midpoint_strategy.live_shadow_ui" not in text:
        # Insert beside the known Hilega router import by finding its import line.
        lines = text.splitlines()
        idx = next(
            (i for i,l in enumerate(lines)
             if "hilega_milega_live_shadow_ui_v1" in l and "router" in l),
            None
        )
        if idx is None:
            raise SystemExit("STOP: Hilega live-shadow router import anchor not found in api.py")
        lines.insert(
            idx + 1,
            "from .midpoint_strategy.live_shadow_ui import router as midpoint_strategy_live_shadow_router",
        )
        text = "\n".join(lines) + ("\n" if text.endswith("\n") else "")

    if "app.include_router(midpoint_strategy_live_shadow_router)" not in text:
        text = replace_once(
            text,
            "    app.include_router(hilega_milega_live_shadow_router)",
            "    app.include_router(hilega_milega_live_shadow_router)\n"
            "    app.include_router(midpoint_strategy_live_shadow_router)",
            "api include_router",
        )
    return text


def patch_app(text: str) -> str:
    if "import MidpointStrategyShadow" not in text:
        text = replace_once(
            text,
            "import HilegaMilegaShadow from './hilegaMilegaShadow'",
            "import HilegaMilegaShadow from './hilegaMilegaShadow'\n"
            "import MidpointStrategyShadow from './midpointStrategyShadow'",
            "App import",
        )

    text = text.replace(
        "['PCR workspace','Live shadow','Hilega shadow','Historical replay','Historical research','Data health','Configuration']",
        "['PCR workspace','Live shadow','Hilega shadow','Midpoint Strategy','Historical replay','Historical research','Data health','Configuration']",
        1,
    )

    old_icon = "label==='Hilega shadow'?'◉':label==='Historical replay'?'↺'"
    if old_icon in text:
        text = text.replace(
            old_icon,
            "label==='Hilega shadow'?'◉':label==='Midpoint Strategy'?'◆':label==='Historical replay'?'↺'",
            1,
        )

    old_desc = (
        "tab==='Hilega shadow'?'Hilega-Milega canonical live shadow with ATM±2 lifecycle and detailed audit drill-down.':"
        "tab==='Historical replay'?"
    )
    if old_desc in text:
        text = text.replace(
            old_desc,
            "tab==='Hilega shadow'?'Hilega-Milega canonical live shadow with ATM±2 lifecycle and detailed audit drill-down.':"
            "tab==='Midpoint Strategy'?'Midpoint Strategy shadow workspace with Family B lifecycle and fully auditable decisions.':"
            "tab==='Historical replay'?",
            1,
        )

    old_button_guard = (
        "tab!=='Historical research' && tab!=='Live shadow' && "
        "tab!=='Hilega shadow' && tab!=='Historical replay'"
    )
    if old_button_guard in text:
        text = text.replace(
            old_button_guard,
            "tab!=='Historical research' && tab!=='Live shadow' && "
            "tab!=='Hilega shadow' && tab!=='Midpoint Strategy' && tab!=='Historical replay'",
            1,
        )

    if "{tab==='Midpoint Strategy' && <MidpointStrategyShadow/>}" not in text:
        text = replace_once(
            text,
            "      {tab==='Hilega shadow' && <HilegaMilegaShadow/>}",
            "      {tab==='Hilega shadow' && <HilegaMilegaShadow/>}\n"
            "      {tab==='Midpoint Strategy' && <MidpointStrategyShadow/>}",
            "App workspace render",
        )

    return text


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    for p in (API, APP):
        if not p.exists():
            raise SystemExit(f"STOP: missing expected repo file: {p}")

    api_old = API.read_text()
    app_old = APP.read_text()

    api_new = patch_api(api_old)
    app_new = patch_app(app_old)

    print("MIDPOINT M3 WORKSPACE PATCH")
    print("=" * 80)
    print(f"api.py changed={api_new != api_old}")
    print(f"App.tsx changed={app_new != app_old}")
    print("route=/api/live-shadow/midpoint-strategy")
    print("workspace=Midpoint Strategy")

    if not args.apply:
        print("DRY RUN ONLY. Re-run with --apply after review.")
        return

    for p in (API, APP):
        backup = p.with_suffix(p.suffix + ".pre-midpoint-m3.bak")
        if not backup.exists():
            shutil.copy2(p, backup)

    API.write_text(api_new)
    APP.write_text(app_new)
    print("APPLIED")
    print("Backups created beside api.py/App.tsx if not already present.")


if __name__ == "__main__":
    main()
