#!/usr/bin/env python3
from __future__ import annotations

import re
from pathlib import Path

TARGET = Path("scripts/midpoint_v58_480_session_be_accounting_validation.py")


def insert_v57_constant(s: str) -> str:
    if "V57 = Path(" in s:
        return s

    # Prefer inserting immediately after the V55/V52/CANON path constants block.
    matches = list(re.finditer(
        r'^(?:V55|V52|CANON)\s*=\s*Path\([^\n]+\)\s*$',
        s,
        re.M,
    ))
    if matches:
        pos = matches[-1].end()
        return s[:pos] + '\nV57 = Path("scripts/midpoint_v57_full_historical_be_lifecycle_replay.py")' + s[pos:]

    # Fallback: insert after pathlib import.
    anchor = "from pathlib import Path\n"
    if anchor in s:
        return s.replace(
            anchor,
            anchor + '\nV57 = Path("scripts/midpoint_v57_full_historical_be_lifecycle_replay.py")\n',
            1,
        )

    raise SystemExit("STOP: could not locate a safe place to insert V57 constant")


def replace_replay_session(s: str) -> str:
    wrapper = (
        'def replay_session(session_date: str, u_day: dict, f_day: dict):\n'
        '    """Reuse the parity-proven V57 replay path."""\n'
        '    v57 = import_module(V57, "v57_replay_for_v58")\n'
        '    rows, open_active, active_family = v57.replay_session(\n'
        '        session_date, u_day, f_day\n'
        '    )\n'
        '    return rows\n\n\n'
    )

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
    return pattern.sub(wrapper, s, count=1)


def main():
    if not TARGET.exists():
        raise SystemExit(f"STOP: missing {TARGET}")

    original = TARGET.read_text()
    updated = insert_v57_constant(original)
    updated = replace_replay_session(updated)

    if updated == original:
        print("No change required.")
        return

    backup = TARGET.with_suffix(TARGET.suffix + ".pre-v58-1-fix2.bak")
    if not backup.exists():
        backup.write_text(original)

    TARGET.write_text(updated)
    print(f"Patched: {TARGET}")
    print("PASS: V58 now delegates historical replay to V57.")
    print("No B/E selection or management rule changed.")


if __name__ == "__main__":
    main()
