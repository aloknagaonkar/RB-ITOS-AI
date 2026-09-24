#!/usr/bin/env python3
from pathlib import Path
from datetime import datetime, timezone
import argparse
import shutil

FILES = [
    Path("backend/market_lab/hilega_directional_ce_historical_shadow_v1.py"),
    Path("backend/market_lab/hilega_directional_ce_historical_shadow_cli_v1.py"),
    Path("backend/market_lab/hilega_directional_historical_ui_v1.py"),
    Path("tests/test_hilega_directional_ce_historical_shadow_v1.py"),
    Path("tests/test_hilega_directional_historical_ui_v2.py"),
]


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--repo", required=True)
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument("--check", action="store_true")
    g.add_argument("--apply", action="store_true")
    a = p.parse_args()

    repo = Path(a.repo).resolve()
    payload = Path(__file__).resolve().parent/"files"

    required = [
        repo/"backend/market_lab/hilega_milega_option_candidate_v1.py",
        repo/"backend/market_lab/hilega_milega_option_shadow_lifecycle_v1.py",
        repo/"backend/market_lab/hilega_directional_historical_ui_v1.py",
        repo/"backend/market_lab/hilega_directional_pe_historical_shadow_v1.py",
    ]
    missing = [str(x) for x in required if not x.is_file()]
    if missing:
        raise SystemExit("BLOCKED: required files missing:\n" + "\n".join(missing))

    print("READY")
    print("  - adds bullish CE ATM-2..ATM+2 historical shadow")
    print("  - reuses existing frozen CE candidate builder")
    print("  - reuses existing frozen CE option lifecycle")
    print("  - exact 1m entry/exit OPEN semantics")
    print("  - no nearest strike/minute fallback")
    print("  - no strategy/coordinator changes")
    print("  - historical UI reads CE shadow + PE shadow")
    print("  - no frontend change")
    print("  - no Hilega worker restart")
    if a.check:
        print("CHECK PASS")
        return

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup = repo/".hilega-directional-ce-historical-shadow-ui-v1-backup"/stamp
    for rel in FILES:
        dst = repo/rel
        if dst.exists():
            b = backup/rel
            b.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(dst, b)

    for rel in FILES:
        src = payload/rel
        dst = repo/rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)

    print("APPLY PASS")
    print("Backup:", backup)
    print("No frontend rebuild required.")
    print("API restart required only after CE evidence is generated because historical router code changed.")
    print("DO NOT restart Hilega live-shadow worker.")


if __name__ == "__main__":
    main()
