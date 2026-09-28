#!/usr/bin/env python3
from __future__ import annotations

import argparse
import importlib.util
import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping

V55 = Path("scripts/midpoint_v55_boundary_selection_replay.py")
V52 = Path("scripts/midpoint_mature_boundary_robustness_v52_1.py")
CANON = Path("scripts/midpoint_vwap_60_session_setup_family_validation_v1_1.py")
V57 = Path("scripts/midpoint_v57_full_historical_be_lifecycle_replay.py")
OUT = Path("data/historical-evidence/hilega-pcr-oi-support-research-v1/midpoint-ui-replay-v1")


def load_module(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Could not load module: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _field(row: Any, name: str):
    if row is None:
        return None
    if isinstance(row, Mapping):
        return row.get(name)
    return getattr(row, name, None)


def _number(value: Any):
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return value


def _timestamp_text(day: str, key: Any, row: Any = None) -> str:
    candidates = [
        key,
        _field(row, "timestamp"),
        _field(row, "ts"),
        _field(row, "datetime"),
        _field(row, "time"),
    ]
    for value in candidates:
        if value is None:
            continue
        if isinstance(value, datetime):
            text = value.isoformat()
            if value.tzinfo is None:
                text += "+05:30"
            return text
        text = str(value).strip()
        if not text:
            continue
        text = text.replace(" ", "T", 1)
        if re.match(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}$", text):
            return text + ":00+05:30"
        if re.match(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}$", text):
            return text + "+05:30"
        if re.match(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}", text):
            return text
        if re.match(r"^\d{2}:\d{2}$", text):
            return f"{day}T{text}:00+05:30"
        if re.match(r"^\d{2}:\d{2}:\d{2}$", text):
            return f"{day}T{text}+05:30"
    return f"{day}T00:00:00+05:30"


def _minute_rows(day: str, u_day: dict, f_day: dict) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for key in sorted(set(u_day).union(f_day), key=lambda x: _timestamp_text(day, x, u_day.get(x) or f_day.get(x))):
        underlying = u_day.get(key)
        futures = f_day.get(key)
        timestamp = _timestamp_text(day, key, underlying or futures)
        rows.append(
            {
                "session_date": day,
                "timestamp": timestamp,
                "underlying_open": _number(_field(underlying, "open")),
                "underlying_high": _number(_field(underlying, "high")),
                "underlying_low": _number(_field(underlying, "low")),
                "underlying_close": _number(_field(underlying, "close")),
                "futures_close": _number(_field(futures, "close")),
                "futures_vwap": _number(_field(futures, "vwap")),
                "data_status": (
                    "BOTH"
                    if underlying is not None and futures is not None
                    else "UNDERLYING_ONLY"
                    if underlying is not None
                    else "FUTURES_ONLY"
                ),
            }
        )
    return rows


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", default="")
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()

    v55 = load_module(V55, "v55_m22")
    v52 = load_module(V52, "v52_m22")
    canon = load_module(CANON, "canon_m22")
    v57 = load_module(V57, "v57_m22")

    OUT.mkdir(parents=True, exist_ok=True)
    indexed: dict[str, dict[str, Any]] = {}
    written = 0

    for block in v52.BLOCKS:
        u, fut, framework = v55.load_block(block, v52, canon)
        for day in sorted(set(u).intersection(fut)):
            if args.date and day != args.date:
                continue

            session_dir = OUT / day
            audit_path = session_dir / "audit.jsonl"
            minutes_path = session_dir / "minutes.jsonl"
            metadata_path = session_dir / "metadata.json"
            needs_write = args.force or not audit_path.exists() or not minutes_path.exists()

            if args.limit and written >= args.limit and needs_write:
                break

            session_dir.mkdir(parents=True, exist_ok=True)
            existing_meta = json.loads(metadata_path.read_text()) if metadata_path.exists() else {}

            if args.force or not audit_path.exists():
                audit_rows, open_active, active_family = v57.replay_session(day, u[day], fut[day])
                _write_jsonl(audit_path, audit_rows)
            else:
                audit_rows = [json.loads(line) for line in audit_path.read_text().splitlines() if line.strip()]
                open_active = existing_meta.get("open_active", False)
                active_family = existing_meta.get("active_family")

            if args.force or not minutes_path.exists():
                minute_rows = _minute_rows(day, u[day], fut[day])
                _write_jsonl(minutes_path, minute_rows)
            else:
                minute_rows = [json.loads(line) for line in minutes_path.read_text().splitlines() if line.strip()]

            if needs_write:
                written += 1
                print(
                    day,
                    "events=", len(audit_rows),
                    "minutes=", len(minute_rows),
                    "block=", block["name"],
                )

            timestamps = [str(x.get("timestamp") or "") for x in minute_rows if x.get("timestamp")]
            meta = {
                "session_date": day,
                "block": block["name"],
                "event_count": len(audit_rows),
                "minute_count": len(minute_rows),
                "first_minute": min(timestamps) if timestamps else None,
                "last_minute": max(timestamps) if timestamps else None,
                "open_active": bool(open_active),
                "active_family": active_family,
                "source": "V57_PARITY_PROVEN_REPLAY",
                "minute_source": "V55_LOAD_BLOCK_UNDERLYING_AND_FUTURES",
            }
            metadata_path.write_text(json.dumps(meta, indent=2) + "\n")
            indexed[day] = {
                "session_date": day,
                "block": block["name"],
                "event_count": len(audit_rows),
                "minute_count": len(minute_rows),
                "first_minute": meta["first_minute"],
                "last_minute": meta["last_minute"],
                "source": "V57_PARITY_PROVEN_REPLAY",
                "status": "AVAILABLE",
            }

        if args.limit and written >= args.limit:
            break

    for session_dir in OUT.iterdir():
        if not session_dir.is_dir() or not (session_dir / "audit.jsonl").exists() or session_dir.name in indexed:
            continue
        metadata_path = session_dir / "metadata.json"
        meta = json.loads(metadata_path.read_text()) if metadata_path.exists() else {}
        minutes_path = session_dir / "minutes.jsonl"
        minute_count = meta.get("minute_count")
        if minute_count is None and minutes_path.exists():
            minute_count = sum(1 for line in minutes_path.open() if line.strip())
        event_count = meta.get("event_count")
        if event_count is None:
            event_count = sum(1 for line in (session_dir / "audit.jsonl").open() if line.strip())
        indexed[session_dir.name] = {
            "session_date": session_dir.name,
            "block": meta.get("block"),
            "event_count": event_count,
            "minute_count": minute_count,
            "first_minute": meta.get("first_minute"),
            "last_minute": meta.get("last_minute"),
            "source": meta.get("source", "V57_PARITY_PROVEN_REPLAY"),
            "status": "AVAILABLE" if minutes_path.exists() else "EVENTS_ONLY",
        }

    manifest = {
        "model": "MIDPOINT_UI_REPLAY_MANIFEST_V1",
        "source": "V57_PARITY_PROVEN_REPLAY",
        "session_count": len(indexed),
        "sessions": sorted(indexed.values(), key=lambda x: x["session_date"], reverse=True),
    }
    (OUT / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    print("manifest sessions=", len(indexed))


if __name__ == "__main__":
    main()
