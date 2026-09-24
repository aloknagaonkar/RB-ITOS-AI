#!/usr/bin/env python3
from pathlib import Path
import argparse, shutil
from datetime import datetime, timezone

REL = Path("backend/market_lab/hilega_historical_ui_api_v1.py")

OLD = r"""
        complete = _live_is_complete(day_rows)
        # Today's live session becomes historical automatically only after the
        # strategy/session lock is actually recorded. Older incomplete evidence
        # remains discoverable as PARTIAL rather than being silently lost.
        if day == today and not complete:
            continue
        found.append({
"""

NEW = r"""
        complete = _live_is_complete(day_rows)
        is_today = day == today
        # Keep the active trading day visible in the session registry so the
        # historical/session UI can reuse the same canonical candle renderer.
        # Active evidence is explicitly LIVE/PARTIAL; no evidence is rewritten.
        found.append({
"""

OLD_STATUS = r"""
            "evidence_level": "FULL" if complete else "PARTIAL",
            "status": "COMPLETE" if complete else "PARTIAL",
"""

NEW_STATUS = r"""
            "evidence_level": "FULL" if complete else "PARTIAL",
            "status": "COMPLETE" if complete else ("LIVE" if is_today else "PARTIAL"),
"""

def main():
    ap = argparse.ArgumentParser(description="Expose active Hilega live day in session registry")
    ap.add_argument("--repo", required=True)
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--check", action="store_true")
    g.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    repo = Path(args.repo).resolve()
    path = repo / REL
    if not path.is_file():
        print(f"BLOCKED: missing {REL}")
        raise SystemExit(2)

    text = path.read_text(encoding="utf-8")

    already = (NEW in text and NEW_STATUS in text and OLD not in text and OLD_STATUS not in text)
    if already:
        print("ALREADY_PATCHED:", REL)
        return

    if OLD not in text:
        print("BLOCKED: expected current-day skip block was not found exactly.")
        print("No file changed.")
        raise SystemExit(2)
    if OLD_STATUS not in text:
        print("BLOCKED: expected live status block was not found exactly.")
        print("No file changed.")
        raise SystemExit(2)

    print("READY:", REL)
    print("  - active current day will be retained")
    print("  - active current day status will be LIVE")
    print("  - evidence_level remains PARTIAL until existing completion logic says complete")
    print("  - prior incomplete live days remain PARTIAL")
    print("  - append-only evidence and strategy logic are untouched")

    if args.check:
        print("CHECK PASS")
        return

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup = repo / ".hilega-live-session-visibility-backup" / stamp / REL
    backup.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(path, backup)

    patched = text.replace(OLD, NEW, 1).replace(OLD_STATUS, NEW_STATUS, 1)
    path.write_text(patched, encoding="utf-8")

    verify = path.read_text(encoding="utf-8")
    if NEW not in verify or NEW_STATUS not in verify or OLD in verify or OLD_STATUS in verify:
        shutil.copy2(backup, path)
        print("BLOCKED: post-write verification failed; original restored.")
        raise SystemExit(2)

    print("APPLY PASS")
    print("Backup:", backup)
    print("Restart only the API process after tests. Do NOT restart the Hilega worker.")

if __name__ == "__main__":
    main()
