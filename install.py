#!/usr/bin/env python3
from pathlib import Path
import argparse
import shutil
from datetime import datetime, timezone

COPY_FILES = [
    Path("backend/market_lab/hilega_directional_trade_dashboard_v1.py"),
    Path("backend/market_lab/hilega_directional_live_shadow_ui_v1.py"),
    Path("tests/test_hilega_directional_trade_dashboard_v1.py"),
    Path("frontend/src/hilegaMilegaShadow.tsx"),
]

API = Path("backend/market_lab/api.py")
IMPORT_ANCHOR = "from .hilega_milega_live_shadow_ui_v1 import router as hilega_milega_live_shadow_router\n"
IMPORT_LINE = "from .hilega_directional_live_shadow_ui_v1 import router as hilega_directional_live_shadow_router\n"
INCLUDE_ANCHOR = "    app.include_router(hilega_milega_live_shadow_router)\n"
INCLUDE_LINE = "    app.include_router(hilega_directional_live_shadow_router)\n"


def patch_api(text: str) -> str:
    if IMPORT_LINE not in text:
        if IMPORT_ANCHOR not in text:
            raise RuntimeError("API_IMPORT_ANCHOR_NOT_FOUND")
        text = text.replace(IMPORT_ANCHOR, IMPORT_ANCHOR + IMPORT_LINE, 1)
    if INCLUDE_LINE not in text:
        if INCLUDE_ANCHOR not in text:
            raise RuntimeError("API_ROUTER_ANCHOR_NOT_FOUND")
        text = text.replace(INCLUDE_ANCHOR, INCLUDE_ANCHOR + INCLUDE_LINE, 1)
    return text


def main():
    ap = argparse.ArgumentParser(description="Install Hilega directional combined UI Phase 6 v1")
    ap.add_argument("--repo", required=True)
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--check", action="store_true")
    g.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    repo = Path(args.repo).resolve()
    root = Path(__file__).resolve().parent

    required = [
        repo/API,
        repo/"backend/market_lab/hilega_directional_live_shadow_v1.py",
        repo/"backend/market_lab/hilega_directional_coordinator_v1.py",
        repo/"frontend/src/hilegaMilegaShadow.tsx",
    ]
    missing = [str(x) for x in required if not x.is_file()]
    if missing:
        print("BLOCKED: required baseline files missing:")
        for x in missing:
            print(" ", x)
        raise SystemExit(2)

    for rel in COPY_FILES:
        if not (root/"files"/rel).is_file():
            print("BLOCKED: patch payload missing:", rel)
            raise SystemExit(2)

    try:
        candidate = patch_api((repo/API).read_text(encoding="utf-8"))
    except RuntimeError as exc:
        print("BLOCKED:", exc)
        raise SystemExit(2)

    print("READY")
    print("  - adds read-only /api/live-shadow/hilega-directional endpoints")
    print("  - exposes coordinator owner + bullish/bearish state + accepted/suppressed events")
    print("  - combines bullish CE and bearish PE ATM±2 lifecycle projection")
    print("  - frontend reads direction from coordinator audit; never infers direction")
    print("  - no selector, quantity, rupee P&L, paper orders or execution")
    print("  - no strategy/coordinator/live-worker behavior change")
    print("  - active bootstrap UPDATE can project the recovered current trade without inventing a START")
    print("  - earlier exited trades absent from directional audit are not fabricated")
    print("  - activation requires frontend build + targeted API restart only")
    if args.check:
        print("CHECK PASS")
        return

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup_root = repo/".hilega-directional-ui-phase6-v1-backup"/stamp

    # Back up copied destinations and API before mutation.
    for rel in [*COPY_FILES, API]:
        src = repo/rel
        if src.exists():
            dst = backup_root/rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)

    for rel in COPY_FILES:
        src = root/"files"/rel
        dst = repo/rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)

    (repo/API).write_text(candidate, encoding="utf-8")

    print("APPLY PASS")
    print("Backup root:", backup_root)
    print("Do NOT restart the Hilega live-shadow worker.")
    print("Build frontend, then restart only the API process.")

if __name__ == "__main__":
    main()
