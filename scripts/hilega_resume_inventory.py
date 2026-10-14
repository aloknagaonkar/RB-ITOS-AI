"""Read-only inventory for Hilega option research and manual-exit dispatch.

Run from the repository root on the strategy VM. Output contains file paths,
coverage metadata, and event summaries; it omits order payloads and credentials.
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path


OPTION_MARKERS = ("option", "contract", "directional-market-evidence")
EVENT_FILES = {
    "step_audit": "data/live-observation/hilega-directional-v1/step-audit.jsonl",
    "bridge_intents": "data/live-observation/hilega-upstox-sandbox-v1/would-submit.jsonl",
    "basket_events": "data/live-observation/hilega-upstox-sandbox-v2/basket-events.jsonl",
    "manual_exit": "data/live-observation/hilega-upstox-sandbox-v2/manual-exit.json",
    "manual_reset_acks": "data/live-observation/hilega-upstox-sandbox-v2/manual-reset-acks.json",
}


def read_json(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return {"read_error": type(exc).__name__}


def jsonl_rows(path: Path):
    if not path.is_file():
        return []
    rows = []
    try:
        with path.open(encoding="utf-8") as handle:
            for line in handle:
                if line.strip():
                    rows.append(json.loads(line))
    except (OSError, ValueError) as exc:
        return [{"read_error": type(exc).__name__}]
    return rows


def option_inventory(data_root: Path):
    files = [p for p in data_root.rglob("*") if p.is_file()]
    candidates = [
        p for p in files
        if any(marker in str(p.relative_to(data_root)).lower() for marker in OPTION_MARKERS)
    ]
    caches = []
    for path in candidates:
        if not any(part.startswith("historical-option-ohlc-cache") for part in path.parts):
            continue
        item = {"path": str(path), "bytes": path.stat().st_size}
        if path.suffix.lower() == ".json":
            payload = read_json(path)
            if isinstance(payload, dict):
                item.update({k: payload.get(k) for k in ("status", "session_date", "expiry", "row_count", "wings")})
                rows = payload.get("rows")
                if isinstance(rows, list):
                    item["actual_rows"] = len(rows)
                    item["rows_by_side"] = dict(sorted(Counter(
                        str(row.get("side", "?")).upper() for row in rows
                        if isinstance(row, dict)
                    ).items()))
                    item["unique_contracts_by_side"] = dict(sorted(Counter(
                        side for side, _ in {
                            (str(row.get("side", "?")).upper(), str(row.get("instrument_key", "")))
                            for row in rows if isinstance(row, dict)
                        }
                    ).items()))
        caches.append(item)
    return {
        "total_data_files": len(files),
        "option_named_files": len(candidates),
        "option_named_paths": [str(p) for p in candidates[:100]],
        "option_named_paths_truncated": len(candidates) > 100,
        "historical_option_ohlc_caches": caches,
    }


def event_inventory(root: Path, day: str, start: str, end: str):
    paths = {name: root / relative for name, relative in EVENT_FILES.items()}
    available = {name: path.is_file() for name, path in paths.items()}
    window_start, window_end = f"{day}T{start}", f"{day}T{end}"

    def in_window(value):
        return bool(value) and window_start <= str(value)[:16] <= window_end

    audit = []
    for row in jsonl_rows(paths["step_audit"]):
        payload = row.get("payload") or {}
        timestamp = payload.get("decision_timestamp") or row.get("checkpoint") or row.get("event_time")
        if in_window(timestamp):
            audit.append({
                "sequence": row.get("sequence"), "time": timestamp,
                "stage": row.get("stage"), "status": row.get("status"),
                "strategy_id": payload.get("strategy_id"),
                "accepted_events": payload.get("accepted_events"),
                "request_id": payload.get("request_id"),
                "owner_after": payload.get("trade_owner_after"),
            })
    intents = []
    for row in jsonl_rows(paths["bridge_intents"]):
        if in_window(row.get("event_timestamp")):
            intents.append({k: row.get(k) for k in (
                "source_sequence", "event_timestamp", "event_type", "direction",
                "trade_id", "decision", "reason_code", "strategy_id",
            )})
    basket = []
    all_basket = jsonl_rows(paths["basket_events"])
    for row in all_basket:
        if in_window(row.get("event_timestamp")) or in_window(row.get("timestamp")):
            basket.append({k: row.get(k) for k in (
                "source_sequence", "event_timestamp", "timestamp", "event_type",
                "direction", "trade_id", "status", "reason", "role",
            )})
    manual = read_json(paths["manual_exit"]) if available["manual_exit"] else {}
    requests = manual.get("requests", []) if isinstance(manual, dict) else []
    requests = [{k: r.get(k) for k in (
        "request_id", "status", "requested_at", "completed_at", "ready_at",
        "trade_ids", "last_error",
    )} for r in requests if r.get("session_date") == day]
    acks = read_json(paths["manual_reset_acks"]) if available["manual_reset_acks"] else {}
    return {
        "files_present": available,
        "source_audit_window": audit,
        "bridge_intents_window": intents,
        "basket_events_window": basket,
        "basket_status_counts_for_day": dict(sorted(Counter(
            str(r.get("status")) for r in all_basket if r.get("session_date") == day
        ).items())),
        "manual_requests_for_day": requests,
        "reset_ack_request_ids": sorted(set(acks) & {r["request_id"] for r in requests}) if isinstance(acks, dict) else [],
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path("."))
    parser.add_argument("--day", default="2026-10-14")
    parser.add_argument("--start", default="14:40")
    parser.add_argument("--end", default="15:00")
    args = parser.parse_args()
    root = args.root.resolve()
    print(json.dumps({
        "root": str(root), "day": args.day,
        "option_inventory": option_inventory(root / "data"),
        "dispatch_diagnostic": event_inventory(root, args.day, args.start, args.end),
    }, indent=2, sort_keys=True, default=str))


if __name__ == "__main__":
    main()
