#!/usr/bin/env python3
from pathlib import Path

p = Path("backend/market_lab/midpoint_strategy/live_shadow_ui.py")
if not p.exists():
    raise SystemExit(f"STOP: missing {p}")

text = p.read_text()

old_import = "from fastapi import APIRouter, HTTPException, Query"
new_import = "from typing import Annotated\n\nfrom fastapi import APIRouter, HTTPException, Query"
if "from typing import Annotated" not in text:
    if old_import not in text:
        raise SystemExit("STOP: FastAPI import anchor not found")
    text = text.replace(old_import, new_import, 1)

old_events = '''def events(
    limit: int = Query(default=200, ge=1, le=2000),
    event_type: str | None = None,
):'''
new_events = '''def events(
    limit: Annotated[int, Query(ge=1, le=2000)] = 200,
    event_type: str | None = None,
):'''
if old_events in text:
    text = text.replace(old_events, new_events, 1)
elif new_events not in text:
    raise SystemExit("STOP: events() anchor not found")

old_timeline = '''def timeline(limit: int = Query(default=500, ge=1, le=5000)):'''
new_timeline = '''def timeline(
    limit: Annotated[int, Query(ge=1, le=5000)] = 500,
):'''
if old_timeline in text:
    text = text.replace(old_timeline, new_timeline, 1)
elif new_timeline not in text:
    raise SystemExit("STOP: timeline() anchor not found")

p.write_text(text)
print(f"PATCHED: {p}")
print("FastAPI HTTP validation preserved; direct Python calls now receive integer defaults.")
