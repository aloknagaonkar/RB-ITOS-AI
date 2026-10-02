#!/usr/bin/env python3
from __future__ import annotations
import re
from pathlib import Path

TARGET = Path("scripts/midpoint_v58_480_session_be_accounting_validation.py")
IMPORT_ANCHOR = 'CANON = Path("scripts/midpoint_vwap_60_session_setup_family_validation_v1_1.py")\n'
IMPORT_INSERT = (
    'CANON = Path("scripts/midpoint_vwap_60_session_setup_family_validation_v1_1.py")\n'
    'V57 = Path("scripts/midpoint_v57_full_historical_be_lifecycle_replay.py")\n'
)

WRAPPER = (
    'def replay_session(session_date: str, u_day: dict, f_day: dict):\n'
    '    """Reuse the parity-proven V57 replay path."""\n'
    '    v57 = import_module(V57, "v57_replay_for_v58")\n'
    '    rows, open_active, active_family = v57.replay_session(\n'
    '        session_date, u_day, f_day\n'
    '    )\n'
    '    return rows\n\n\n'
)

def main():
    if not TARGET.exists():
        raise SystemExit(f"STOP: missing {TARGET}")
    s = TARGET.read_text()

    if 'V57 = Path(' not in s:
        if IMPORT_ANCHOR not in s:
            raise SystemExit("STOP: V57 import anchor not found")
        s = s.replace(IMPORT_ANCHOR, IMPORT_INSERT, 1)

    pattern = re.compile(
        r'^def replay_session\(session_date: str, u_day: dict, f_day: dict\):\n'
        r'.*?(?=^def [A-Za-z_]\w*\()',
        re.M | re.S,
    )
    matches = list(pattern.finditer(s))
    if len(matches) != 1:
        raise SystemExit(
            f"STOP: expected exactly one replay_session function, found {len(matches)}"
        )
    s = pattern.sub(WRAPPER, s, count=1)

    backup = TARGET.with_suffix(TARGET.suffix + ".pre-v58-1.bak")
    if not backup.exists():
        backup.write_text(TARGET.read_text())
    TARGET.write_text(s)

    print(f"Patched: {TARGET}")
    print("V58 now reuses V57 parity-proven replay_session.")
    print("No strategy or management rule changed.")

if __name__ == "__main__":
    main()
