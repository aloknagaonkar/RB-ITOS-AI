#!/usr/bin/env python3
from __future__ import annotations

import re
from pathlib import Path

TARGET = Path("scripts/midpoint_v58_480_session_be_accounting_validation.py")


def main():
    if not TARGET.exists():
        raise SystemExit(f"STOP: missing {TARGET}")

    original = TARGET.read_text()
    s = original

    # Current V58 exact constants are single-quoted and use replay(day,u,fut).
    if "V57 = Path(" not in s:
        anchor = "CANON = Path('scripts/midpoint_vwap_60_session_setup_family_validation_v1_1.py')\n"
        if anchor not in s:
            raise SystemExit("STOP: exact CANON anchor not found")
        s = s.replace(
            anchor,
            anchor + "V57 = Path('scripts/midpoint_v57_full_historical_be_lifecycle_replay.py')\n",
            1,
        )

    wrapper = (
        "def replay(day,u,fut):\n"
        "    \"\"\"Reuse V57 parity-proven replay path exactly.\"\"\"\n"
        "    v57=load_module(V57,'v57_replay_v58')\n"
        "    rows, open_active, active_family = v57.replay_session(day,u,fut)\n"
        "    return rows\n\n"
    )

    pattern = re.compile(
        r"^def replay\(day,u,fut\):\n"
        r".*?(?=^def bars\(u,start,end=None\):)",
        re.M | re.S,
    )
    matches = list(pattern.finditer(s))
    if len(matches) != 1:
        raise SystemExit(
            f"STOP: expected exactly one current replay(day,u,fut) function, found {len(matches)}"
        )

    s = pattern.sub(wrapper, s, count=1)

    backup = TARGET.with_suffix(TARGET.suffix + ".pre-v58-1-fix3.bak")
    if not backup.exists():
        backup.write_text(original)

    TARGET.write_text(s)

    print(f"Patched: {TARGET}")
    print("PASS: V58 replay(day,u,fut) now delegates to V57 replay_session.")
    print("No accounting logic changed.")
    print("No B/E ownership, CAP20, re-entry, or structural-terminal rule changed.")


if __name__ == "__main__":
    main()
