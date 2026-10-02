#!/usr/bin/env python3
from pathlib import Path
import re

print("MIDPOINT V62.1 PRE-FLIGHT")
print("=" * 80)

targets = [
    Path("backend/market_lab/live_shadow_worker_v1.py"),
    Path("backend/market_lab/midpoint_strategy/live_shadow_v1.py"),
]

for p in targets:
    print(f"\n--- {p} ---")
    if not p.exists():
        print("MISSING")
        continue
    txt = p.read_text()
    for pat in [
        r"audit_path",
        r"_process_minute",
        r"underlying",
        r"jsonl",
        r"live-observation",
    ]:
        hits = [i+1 for i, line in enumerate(txt.splitlines()) if re.search(pat, line, re.I)]
        print(f"{pat}: {hits[:30]}")

print("\nNo files changed.")
print("Use this output to wire the adapter to the existing worker safely.")
