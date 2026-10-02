#!/usr/bin/env python3
from pathlib import Path
import shutil

MID_API = Path("backend/market_lab/midpoint_strategy/live_shadow_ui.py")
MID_UI = Path("frontend/src/midpointStrategyShadow.tsx")
MID_CSS = Path("frontend/src/midpointStrategyShadow.css")
MAT = Path("scripts/midpoint_m2_materialize_historical_replay.py")
HILEGA_API = Path("backend/market_lab/hilega_milega_live_shadow_ui_v1.py")
PAYLOAD = Path("patches/midpoint_m2")

def backup(path):
    b = path.with_suffix(path.suffix + ".pre-m2.bak")
    if path.exists() and not b.exists():
        shutil.copy2(path, b)

def install(src, dst):
    backup(dst)
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)
    print("Updated:", dst)

def patch_hilega():
    s = HILEGA_API.read_text()
    if "def _recent_session_rows(" in s:
        print("Hilega recent-two filter already present.")
        return
    anchor = "def _rows() -> list[dict[str, Any]]:\n    return _store().read_all() if STEP_AUDIT_PATH.exists() else []\n"
    if anchor not in s:
        raise SystemExit("STOP: Hilega _rows anchor not found")
    repl = '''def _all_rows() -> list[dict[str, Any]]:
    return _store().read_all() if STEP_AUDIT_PATH.exists() else []


def _row_session_date(row: dict[str, Any]) -> str | None:
    payload = row.get("payload") or {}
    for value in (
        row.get("checkpoint"), row.get("event_time"), row.get("bar_timestamp"), row.get("signal_bar"),
        payload.get("checkpoint"), payload.get("event_time"), payload.get("bar_timestamp"), payload.get("signal_bar"),
    ):
        text = str(value or "")
        if len(text) >= 10 and text[4:5] == "-" and text[7:8] == "-":
            return text[:10]
    return None


def _recent_session_rows(rows: list[dict[str, Any]], keep: int = 2) -> list[dict[str, Any]]:
    days = sorted({d for row in rows if (d := _row_session_date(row))}, reverse=True)
    allowed = set(days[:keep])
    return rows if not allowed else [row for row in rows if _row_session_date(row) in allowed]


def _rows() -> list[dict[str, Any]]:
    return _recent_session_rows(_all_rows(), keep=2)
'''
    backup(HILEGA_API)
    HILEGA_API.write_text(s.replace(anchor, repl, 1))
    print("Patched recent-two filter:", HILEGA_API)

def main():
    install(PAYLOAD/"backend/live_shadow_ui.py", MID_API)
    install(PAYLOAD/"frontend/midpointStrategyShadow.tsx", MID_UI)
    install(PAYLOAD/"frontend/midpointStrategyShadow.css", MID_CSS)
    install(PAYLOAD/"backend/historical_replay_materializer.py", MAT)
    patch_hilega()
    print("PASS: M2 installed. No strategy logic changed.")

if __name__ == "__main__":
    main()
