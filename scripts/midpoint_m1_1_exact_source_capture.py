#!/usr/bin/env python3
from __future__ import annotations

import re
from pathlib import Path

FILES = [
    Path("frontend/src/hilegaMilegaShadow.tsx"),
    Path("frontend/src/hilegaHistoricalReplay.tsx"),
    Path("frontend/src/midpointStrategyShadow.tsx"),
    Path("frontend/src/liveShadow.css"),
    Path("backend/market_lab/hilega_milega_live_shadow_ui_v1.py"),
    Path("backend/market_lab/hilega_historical_ui_api_v1.py"),
    Path("backend/market_lab/midpoint_strategy/live_shadow_ui.py"),
]

KEYS = [
    r"fetch\(",
    r"/api/",
    r"session",
    r"historical",
    r"replay",
    r"audit",
    r"inspect",
    r"detail",
    r"return \{",
    r"@router\.(get|post)",
    r"APIRouter",
    r"read_all",
    r"slice\(",
    r"sort\(",
]

def print_window(path: Path, lines: list[str], start: int, end: int):
    start = max(1, start)
    end = min(len(lines), end)
    print(f"\n### {path} lines {start}-{end}")
    for i in range(start, end + 1):
        print(f"{i:5}: {lines[i-1]}")

def main():
    print("MIDPOINT M1.1 — EXACT SOURCE CAPTURE")
    print("=" * 110)
    print("READ-ONLY: no files changed.")

    for path in FILES:
        print("\n" + "=" * 110)
        print(path)
        print("=" * 110)
        if not path.exists():
            print("MISSING")
            continue

        text = path.read_text(errors="replace")
        lines = text.splitlines()
        print(f"lines={len(lines)}")

        # Always show head/imports/types.
        print_window(path, lines, 1, min(80, len(lines)))

        # Print focused windows around useful anchors.
        anchors = []
        for i, line in enumerate(lines, 1):
            if any(re.search(k, line, re.I) for k in KEYS):
                anchors.append(i)

        # De-duplicate overlapping windows.
        windows = []
        for i in anchors:
            s, e = max(1, i - 8), min(len(lines), i + 18)
            if windows and s <= windows[-1][1] + 5:
                windows[-1] = (windows[-1][0], max(windows[-1][1], e))
            else:
                windows.append((s, e))

        for s, e in windows[:16]:
            print_window(path, lines, s, e)

        # Always show tail to catch exports/router registrations.
        if len(lines) > 80:
            print_window(path, lines, max(1, len(lines)-80), len(lines))

    print("\n" + "=" * 110)
    print("NEXT")
    print("=" * 110)
    print("Paste this output. The next artifact will be the actual implementation patch:")
    print("- Hilega live: today + previous trading session")
    print("- Midpoint live: today + previous trading session")
    print("- Midpoint replay API/date list")
    print("- Midpoint replay reuses the same renderer as live")
    print("- audit detail/inspect patterned after Hilega")
    print("- no strategy logic changes")

if __name__ == "__main__":
    main()
