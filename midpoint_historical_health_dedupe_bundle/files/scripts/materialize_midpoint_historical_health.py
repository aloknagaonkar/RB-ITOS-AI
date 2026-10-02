#!/usr/bin/env python3
"""Materialize causal Midpoint trade health beside immutable replay audits.

The command writes only ``trade-health.jsonl``.  Existing audit/minute files,
entries, exits, option evidence and the live runtime are never changed.
"""

from __future__ import annotations

import argparse
import json
import tempfile
from collections import Counter
from pathlib import Path

from market_lab.midpoint_strategy.entry_health_live_v1 import MidpointEntryHealthLiveV1
from market_lab.midpoint_strategy.historical_health_v1 import (
    MODEL,
    build_historical_health_overlay,
)
from market_lab.midpoint_strategy.replay import load_audit_jsonl


DEFAULT_ROOT = Path(
    "data/historical-evidence/hilega-pcr-oi-support-research-v1/"
    "midpoint-ui-replay-v1"
)

OVERLAY_HEALTH_TYPES = {
    "PRE_ENTRY_HEALTH_SNAPSHOT",
    "ENTRY_HEALTH_SNAPSHOT",
    "CONTINUOUS_HEALTH_CHECK",
    "T5_HEALTH_CHECK",
    "T5_HEALTH_UNAVAILABLE",
    "T5_PROVED_BYPASS",
}


def _health_identity(row: dict) -> tuple:
    """Semantic identity shared by recorded and reconstructed health rows."""
    event_type = str(row.get("event_type") or "")
    # Any live-recorded exact-T+5 outcome is authoritative.  A reconstruction
    # must not replace UNAVAILABLE/BYPASS with a different hindsight outcome.
    type_identity = "T5_HEALTH_OUTCOME" if event_type in {
        "T5_HEALTH_CHECK", "T5_HEALTH_UNAVAILABLE", "T5_PROVED_BYPASS"
    } else event_type
    return (
        row.get("event_timestamp"),
        type_identity,
        row.get("direction"),
        row.get("reference_type"),
        row.get("family"),
    )


def remove_recorded_health(
    generated: list[dict], audit: list[dict]
) -> tuple[list[dict], int]:
    """Prefer immutable live-recorded health; fill only missing observations.

    A Counter is required because repeated/rearmed lanes can legitimately have
    more than one observation with the same semantic identity in one minute.
    """
    recorded = Counter(
        _health_identity(row)
        for row in audit
        if str(row.get("event_type") or "") in OVERLAY_HEALTH_TYPES
    )
    output: list[dict] = []
    duplicates = 0
    for row in generated:
        identity = _health_identity(row)
        if recorded[identity] > 0:
            recorded[identity] -= 1
            duplicates += 1
        else:
            output.append(row)
    return output, duplicates


def _read_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def _write_atomic(path: Path, rows: list[dict]) -> None:
    with tempfile.NamedTemporaryFile(
        mode="w", encoding="utf-8", dir=path.parent,
        prefix=path.name + ".", suffix=".tmp", delete=False,
    ) as handle:
        for row in rows:
            handle.write(json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n")
        temporary = Path(handle.name)
    temporary.replace(path)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--replay-root", type=Path, default=DEFAULT_ROOT)
    parser.add_argument("--dates", nargs="*", default=[])
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()

    manifest_path = args.replay_root / "manifest.json"
    if not manifest_path.exists():
        raise SystemExit(f"STOP: historical manifest unavailable: {manifest_path}")
    manifest = json.loads(manifest_path.read_text())
    available = sorted(
        str(row["session_date"]) for row in manifest.get("sessions", [])
        if row.get("session_date")
    )
    selected = set(args.dates)
    unknown = selected.difference(available)
    if unknown:
        raise SystemExit(f"STOP: dates not present in replay: {sorted(unknown)}")

    # One state across chronological sessions matches the live worker and the
    # original 490-session research: indicator warm-up never sees future bars.
    engine = MidpointEntryHealthLiveV1()
    written = skipped = unavailable = 0
    for day in available:
        directory = args.replay_root / day
        minutes_path = directory / "minutes.jsonl"
        audit_path = directory / "audit.jsonl"
        target = directory / "trade-health.jsonl"
        if not minutes_path.exists() or not audit_path.exists():
            unavailable += 1
            continue
        minutes = _read_jsonl(minutes_path)
        audit = load_audit_jsonl(audit_path)
        generated, engine = build_historical_health_overlay(
            minute_rows=minutes,
            audit_rows=audit,
            engine=engine,
        )
        overlay, recorded_duplicates = remove_recorded_health(generated, audit)
        if selected and day not in selected:
            continue
        if target.exists() and not args.force:
            skipped += 1
            continue
        _write_atomic(target, overlay)
        written += 1
        missing_open = sum(row.get("futures_open") is None for row in minutes)
        missing_volume = sum(row.get("futures_volume") is None for row in minutes)
        print(
            "HEALTH", day, "minutes", len(minutes),
            "generated", len(generated),
            "recorded_live_health_preferred", recorded_duplicates,
            "overlay_fill_events", len(overlay),
            "missing_futures_open", missing_open,
            "missing_futures_volume", missing_volume,
            flush=True,
        )

    report = {
        "model": MODEL,
        "sessions_in_manifest": len(available),
        "selected_dates": sorted(selected),
        "written": written,
        "skipped_existing": skipped,
        "sessions_without_replay_inputs": unavailable,
        "observation_only": True,
        "execution_enabled": False,
        "paper_order_enabled": False,
        "quantity": None,
        "immutable_strategy_audit_modified": False,
    }
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
