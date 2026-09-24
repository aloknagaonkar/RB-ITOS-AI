#!/usr/bin/env python3
from pathlib import Path
from datetime import datetime, timezone
import argparse, shutil

ADD = [
    Path("backend/market_lab/hilega_directional_historical_ui_v1.py"),
    Path("frontend/src/hilegaDirectionalReplayTrades.tsx"),
    Path("tests/test_hilega_directional_historical_ui_v1.py"),
]

API_IMPORT = "from .hilega_directional_historical_ui_v1 import router as hilega_directional_historical_router"
API_ANCHOR = "from .hilega_historical_ui_api_v1 import router as hilega_historical_router"

FRONT_IMPORT = "import HilegaDirectionalReplayTrades from './hilegaDirectionalReplayTrades'"
FRONT_ANCHOR = "import HilegaDecisionTable,{type HilegaAudit} from './hilegaDecisionTable'"

FRONT_INSERT = """      <HilegaDirectionalReplayTrades sessionDate={selectedDate} />

      <HilegaDecisionTable"""
FRONT_TARGET = """      <HilegaDecisionTable"""

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--repo", required=True)
    g=ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--check", action="store_true")
    g.add_argument("--apply", action="store_true")
    a=ap.parse_args()

    repo=Path(a.repo).resolve()
    payload=Path(__file__).resolve().parent/"files"

    api=repo/"backend/market_lab/api.py"
    hist=repo/"frontend/src/hilegaHistoricalReplay.tsx"
    for p in (api,hist):
        if not p.is_file():
            raise SystemExit(f"BLOCKED: required file missing: {p}")

    api_text=api.read_text()
    front_text=hist.read_text()

    if API_IMPORT not in api_text and API_ANCHOR not in api_text:
        raise SystemExit("BLOCKED: api.py Hilega historical router anchor not found")
    if FRONT_IMPORT not in front_text and FRONT_ANCHOR not in front_text:
        raise SystemExit("BLOCKED: historical replay import anchor not found")
    if FRONT_INSERT not in front_text and FRONT_TARGET not in front_text:
        raise SystemExit("BLOCKED: HilegaDecisionTable insertion anchor not found")

    print("READY")
    print("  - keeps existing Historical replay page")
    print("  - adds same CE/PE directional trade cards used conceptually by live shadow")
    print("  - bullish CE from canonical replay audit")
    print("  - bearish PE from recorded directional PE historical shadow")
    print("  - filters option lifecycles to entries accepted by directional replay")
    print("  - no broker calls, no worker restart, no replay rule changes")
    if a.check:
        print("CHECK PASS")
        return

    stamp=datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup=repo/".hilega-directional-historical-ui-v1-backup"/stamp
    for rel in [Path("backend/market_lab/api.py"),Path("frontend/src/hilegaHistoricalReplay.tsx")]:
        dst=backup/rel
        dst.parent.mkdir(parents=True,exist_ok=True)
        shutil.copy2(repo/rel,dst)

    for rel in ADD:
        src=payload/rel
        dst=repo/rel
        dst.parent.mkdir(parents=True,exist_ok=True)
        shutil.copy2(src,dst)

    api_text=api.read_text()
    if API_IMPORT not in api_text:
        api_text=api_text.replace(API_ANCHOR, API_ANCHOR+"\n"+API_IMPORT, 1)

    # Include the router next to the existing Hilega historical router.
    include_anchor="app.include_router(hilega_historical_router)"
    include_line="app.include_router(hilega_directional_historical_router)"
    if include_line not in api_text:
        if include_anchor not in api_text:
            raise SystemExit("BLOCKED during apply: hilega_historical_router include not found")
        api_text=api_text.replace(include_anchor, include_anchor+"\n    "+include_line, 1)
    api.write_text(api_text)

    front_text=hist.read_text()
    if FRONT_IMPORT not in front_text:
        front_text=front_text.replace(FRONT_ANCHOR, FRONT_ANCHOR+"\n"+FRONT_IMPORT, 1)
    if FRONT_INSERT not in front_text:
        front_text=front_text.replace(FRONT_TARGET, FRONT_INSERT, 1)
    hist.write_text(front_text)

    print("APPLY PASS")
    print("Backup:", backup)
    print("Next:")
    print("  PYTHONPATH=backend pytest -q tests/test_hilega_directional_historical_ui_v1.py")
    print("  cd frontend && npm run build")
    print("  restart API only (router added); DO NOT restart Hilega live worker")

if __name__=="__main__":
    main()
