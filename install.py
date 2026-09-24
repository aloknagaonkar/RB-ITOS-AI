#!/usr/bin/env python3
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import argparse
import shutil

NEW_FILES = [
    Path("backend/market_lab/hilega_directional_candle_ui_v1.py"),
    Path("frontend/src/hilegaDirectionalCandleTable.tsx"),
    Path("tests/test_hilega_directional_candle_ui_v1.py"),
]

API_IMPORT = "from .hilega_directional_candle_ui_v1 import router as hilega_directional_candle_router"
API_INCLUDE = "app.include_router(hilega_directional_candle_router)"
FRONT_IMPORT = "import HilegaDirectionalCandleTable from './hilegaDirectionalCandleTable'"
HIST_IMPORT_ANCHOR = "import HilegaDecisionTable,{type HilegaAudit} from './hilegaDecisionTable'"

LIVE_OLD = """      <HilegaDecisionTable reports={rows as HilegaAudit[]} mode="LIVE"
        fetchDetail={detailedAudit}
        emptyMessage="No completed live strategy checkpoints available yet." />"""
LIVE_NEW = """      <HilegaDirectionalCandleTable mode="LIVE" />"""


def patch_historical(text: str) -> str:
    if FRONT_IMPORT not in text:
        if HIST_IMPORT_ANCHOR not in text:
            raise SystemExit("BLOCKED: historical replay import anchor not found")
        text = text.replace(HIST_IMPORT_ANCHOR, HIST_IMPORT_ANCHOR + "\n" + FRONT_IMPORT, 1)

    if '<HilegaDirectionalCandleTable mode="HISTORICAL"' in text:
        return text

    lines = text.splitlines()
    out = []
    i = 0
    replaced = False
    while i < len(lines):
        if "<HilegaDecisionTable" in lines[i]:
            indent = lines[i][:len(lines[i])-len(lines[i].lstrip())]
            while i < len(lines):
                if "/>" in lines[i]:
                    i += 1
                    break
                i += 1
            out.append(f'{indent}<HilegaDirectionalCandleTable mode="HISTORICAL" sessionDate={{selectedDate}} />')
            replaced = True
            continue
        out.append(lines[i])
        i += 1
    if not replaced:
        raise SystemExit("BLOCKED: historical HilegaDecisionTable invocation not found")
    return "\n".join(out) + ("\n" if text.endswith("\n") else "")


def patch_live(text: str) -> str:
    if FRONT_IMPORT not in text:
        if HIST_IMPORT_ANCHOR not in text:
            raise SystemExit("BLOCKED: live shadow import anchor not found")
        text = text.replace(HIST_IMPORT_ANCHOR, HIST_IMPORT_ANCHOR + "\n" + FRONT_IMPORT, 1)
    if LIVE_NEW in text:
        return text
    if LIVE_OLD not in text:
        raise SystemExit("BLOCKED: live HilegaDecisionTable invocation not found")
    return text.replace(LIVE_OLD, LIVE_NEW, 1)


def main():
    p=argparse.ArgumentParser()
    p.add_argument("--repo", required=True)
    g=p.add_mutually_exclusive_group(required=True)
    g.add_argument("--check", action="store_true")
    g.add_argument("--apply", action="store_true")
    a=p.parse_args()

    repo=Path(a.repo).resolve()
    payload=Path(__file__).resolve().parent/"files"
    required=[
        repo/"backend/market_lab/api.py",
        repo/"frontend/src/hilegaHistoricalReplay.tsx",
        repo/"frontend/src/hilegaMilegaShadow.tsx",
    ]
    missing=[str(x) for x in required if not x.is_file()]
    if missing:
        raise SystemExit("BLOCKED: missing required files:\n"+"\n".join(missing))

    api=(repo/"backend/market_lab/api.py").read_text()
    hist=(repo/"frontend/src/hilegaHistoricalReplay.tsx").read_text()
    live=(repo/"frontend/src/hilegaMilegaShadow.tsx").read_text()

    if API_IMPORT not in api and "from .hilega_historical_ui_api_v1 import router as hilega_historical_router" not in api:
        raise SystemExit("BLOCKED: API historical router import anchor not found")
    patch_historical(hist)
    patch_live(live)

    print("READY")
    print("  - historical candle table switches to directional replay rows")
    print("  - bearish ARMED / ENTRY / ACTIVE / EXIT becomes visible")
    print("  - live page shows current-day candle/indicator rows even without a trade")
    print("  - directional owner/state is overlaid where exact live directional bars exist")
    print("  - earlier candles are shown as candle-only; no directional history is invented")
    print("  - no strategy/coordinator/option lifecycle changes")
    print("  - no Hilega live-worker restart")
    if a.check:
        print("CHECK PASS")
        return

    stamp=datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup=repo/".hilega-directional-candle-ui-phase6-2-v1-backup"/stamp
    for rel in [
        Path("backend/market_lab/api.py"),
        Path("frontend/src/hilegaHistoricalReplay.tsx"),
        Path("frontend/src/hilegaMilegaShadow.tsx"),
    ]:
        dst=backup/rel
        dst.parent.mkdir(parents=True,exist_ok=True)
        shutil.copy2(repo/rel,dst)

    for rel in NEW_FILES:
        src=payload/rel
        dst=repo/rel
        dst.parent.mkdir(parents=True,exist_ok=True)
        shutil.copy2(src,dst)

    api_path=repo/"backend/market_lab/api.py"
    api=api_path.read_text()
    if API_IMPORT not in api:
        anchor="from .hilega_historical_ui_api_v1 import router as hilega_historical_router"
        api=api.replace(anchor, anchor+"\n"+API_IMPORT, 1)
    if API_INCLUDE not in api:
        anchor="app.include_router(hilega_historical_router)"
        if anchor not in api:
            raise SystemExit("BLOCKED during apply: historical include_router anchor not found")
        api=api.replace(anchor, anchor+"\n    "+API_INCLUDE, 1)
    api_path.write_text(api)

    hist_path=repo/"frontend/src/hilegaHistoricalReplay.tsx"
    hist_path.write_text(patch_historical(hist_path.read_text()))

    live_path=repo/"frontend/src/hilegaMilegaShadow.tsx"
    live_path.write_text(patch_live(live_path.read_text()))

    print("APPLY PASS")
    print("Backup:",backup)
    print("Next:")
    print("  PYTHONPATH=backend pytest -q tests/test_hilega_directional_candle_ui_v1.py")
    print("  cd frontend && npm run build")
    print("  restart API only")
    print("  DO NOT restart Hilega live-shadow worker")


if __name__=="__main__":
    main()
