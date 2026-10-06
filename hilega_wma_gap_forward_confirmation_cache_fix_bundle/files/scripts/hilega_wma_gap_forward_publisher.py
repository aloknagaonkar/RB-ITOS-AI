#!/usr/bin/env python3
"""Append completed Hilega live sessions to WMA-gap forward confirmation."""
from __future__ import annotations

import argparse
import csv
import hashlib
import importlib.util
import json
import os
import shutil
import sys
import time
from datetime import date, datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from filelock import FileLock, Timeout

ROOT = Path(__file__).resolve().parents[1]
IST = ZoneInfo("Asia/Kolkata")
DEFAULT_AUDIT = Path("data/live-observation/hilega-directional-v1/step-audit.jsonl")
DEFAULT_CACHE = Path("data/historical-evidence/hilega-milega-underlying-cache-v1")
DEFAULT_EVIDENCE = Path("data/live-observation/hilega-directional-market-evidence-v1")
FROZEN_ROOT = Path("data/historical-evidence/hilega-wma-gap-490-v1")
OUTPUT_ROOT = Path("data/historical-evidence/hilega-wma-gap-forward-confirmation-v1")
SESSION_ROOT = OUTPUT_ROOT / "sessions"
LOCK = Path("data/hilega-wma-gap-forward-publisher.lock")
FILES = ("trade-results.csv", "confirmation-attempts.csv", "candidate-timeline.csv")


def load_script(name: str, filename: str):
    path = ROOT / "scripts" / filename
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise ImportError(path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def row_day(row: dict[str, Any]) -> str | None:
    payload = row.get("payload") or {}
    value = payload.get("cutoff_timestamp") or payload.get("bar_timestamp")
    value = str(value or "")
    return value[:10] if len(value) >= 10 else None


def completed_live_sessions(path: Path) -> list[str]:
    completed = set()
    for row in jsonl(path):
        if (str(row.get("stage") or "").upper() == "DIRECTIONAL_SESSION_CUTOFF"
                and str(row.get("status") or "").upper() == "PROCESSED"):
            day = row_day(row)
            if day:
                completed.add(day)
    return sorted(completed)


def csv_rows(path: Path) -> list[dict[str, str]]:
    if not path.is_file() or not path.stat().st_size:
        return []
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("")
        return
    fields: list[str] = []
    for row in rows:
        for key in row:
            if key not in fields:
                fields.append(key)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def frozen_dates(root: Path) -> set[str]:
    return {row["session_date"] for row in csv_rows(root / "trade-results.csv")}


def frozen_last_session(root: Path) -> str | None:
    report = root / "report.json"
    if report.is_file():
        value = (json.loads(report.read_text(encoding="utf-8")).get("sessions") or {}).get(
            "last_session"
        )
        if value:
            return str(value)
    dates = frozen_dates(root)
    return max(dates) if dates else None


def final_recorded_minutes(day: str, evidence_path: Path) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Resolve revised candles by verified journal order; final recording wins."""
    evidence = __import__("market_lab.hilega_market_evidence_v1", fromlist=["verify_journal"])
    recovery = __import__(
        "market_lab.hilega_current_day_directional_recovery_v1", fromlist=["_walk_dicts"]
    )
    if not evidence_path.is_file():
        raise ValueError(f"RECORDED_1M_EVIDENCE_UNAVAILABLE:{day}")
    records = evidence.verify_journal(evidence_path)
    selected: dict[str, dict[str, Any]] = {}
    revisions: set[str] = set()
    observations = 0
    for record in records:
        if record.get("kind") != "underlying" or record.get("status") != "OK":
            continue
        for obj in recovery._walk_dicts(record.get("response")):
            if obj.get("session_date") != day:
                continue
            if obj.get("instrument_key") != "NSE_INDEX|Nifty 50":
                continue
            if int(obj.get("interval_seconds") or 0) != 60:
                continue
            required = ("timestamp", "open", "high", "low", "close")
            if any(obj.get(key) is None for key in required):
                continue
            timestamp = str(obj["timestamp"])
            row = {
                "timestamp": timestamp,
                "open": float(obj["open"]), "high": float(obj["high"]),
                "low": float(obj["low"]), "close": float(obj["close"]),
                "volume": None if obj.get("volume") is None else int(obj["volume"]),
            }
            observations += 1
            if timestamp in selected and selected[timestamp] != row:
                revisions.add(timestamp)
            selected[timestamp] = row
    if not selected:
        raise ValueError(f"RECORDED_1M_EVIDENCE_UNAVAILABLE:{day}")
    return [selected[key] for key in sorted(selected)], {
        "resolution_policy": "FINAL_RECORDED_REVISION_BY_VERIFIED_JOURNAL_SEQUENCE",
        "journal_records": len(records),
        "candle_observations": observations,
        "unique_minutes": len(selected),
        "revised_minutes": len(revisions),
    }


def ensure_recorded_cache(day: str, cache_root: Path, evidence_root: Path) -> dict[str, Any]:
    """Materialize an exact replay cache from immutable live one-minute evidence."""
    audit = load_script("forward_cache_audit", "audit_hilega_indicator_dataset_v2.py")
    target = cache_root / f"{day}.json"

    def validate(path: Path) -> tuple[int, int, list[str]]:
        minutes, _ = audit.load_minutes(path)
        bars, issues = audit.aggregate_five_minute(minutes, date.fromisoformat(day))
        return len(minutes), len(bars), issues

    if target.is_file():
        minute_count, bar_count, issues = validate(target)
        minutes, _ = audit.load_minutes(target)
        bars, _ = audit.aggregate_five_minute(minutes, date.fromisoformat(day))
        strategy_bars = [bar for bar in bars if bar.timestamp.strftime("%H:%M") <= "14:55"]
        if len(strategy_bars) == 69:
            return {"source": "EXISTING_CACHE", "minutes": minute_count, "five_minute_bars": bar_count,
                    "strategy_five_minute_bars": 69, "strategy_window_complete_through": "14:55"}

    evidence = evidence_root / f"{day}.jsonl"
    rows, resolution = final_recorded_minutes(day, evidence)
    cache_root.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(f".json.tmp-{os.getpid()}")
    temporary.write_text(json.dumps({"candles": rows}, indent=2) + "\n", encoding="utf-8")
    minute_count, bar_count, issues = validate(temporary)
    minutes, _ = audit.load_minutes(temporary)
    bars, _ = audit.aggregate_five_minute(minutes, date.fromisoformat(day))
    strategy_bars = [bar for bar in bars if bar.timestamp.strftime("%H:%M") <= "14:55"]
    if len(strategy_bars) != 69:
        temporary.unlink(missing_ok=True)
        issue_names = ",".join(str(item) for item in issues[:3]) or "BAR_COUNT"
        raise ValueError(
            f"RECORDED_CACHE_INCOMPLETE:{day}:minutes={minute_count}:"
            f"five_minute_bars={bar_count}:strategy_bars={len(strategy_bars)}:issues={issue_names}"
        )
    os.replace(temporary, target)
    return {
        "source": "RECORDED_LIVE_1M_EVIDENCE",
        "minutes": minute_count,
        "five_minute_bars": bar_count,
        "strategy_five_minute_bars": 69,
        "strategy_window_complete_through": "14:55",
        **resolution,
    }


def file_sha256(path: Path) -> str | None:
    if not path.is_file():
        return None
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def generate_session(day: str, cache_root: Path) -> tuple[list[dict], list[dict], list[dict]]:
    audit = load_script("forward_indicator_audit", "audit_hilega_indicator_dataset_v2.py")
    alignment = load_script("forward_alignment", "research_hilega_alignment_points_490.py")
    delayed = load_script("forward_delayed", "validate_hilega_wma_delayed_confirmation.py")
    backtest = load_script("forward_wma_gap", "backtest_hilega_wma_gap_490.py")
    bars_by_day = {}
    for path in sorted(cache_root.glob("*.json")):
        try:
            session = date.fromisoformat(path.stem).isoformat()
        except ValueError:
            continue
        if session > day:
            continue
        source_minutes, _ = audit.load_minutes(path)
        bars, issues = audit.aggregate_five_minute(source_minutes, date.fromisoformat(session))
        if session == day:
            bars = [bar for bar in bars if bar.timestamp.strftime("%H:%M") <= "14:55"]
            complete = len(bars) == 69
        else:
            complete = not issues and len(bars) == 75
        if complete:
            bars_by_day[session] = bars
    if day not in bars_by_day:
        raise ValueError(f"COMPLETE_STRATEGY_WINDOW_UNAVAILABLE:{day}:required_through=14:55")
    features, _ = audit.feature_rows(
        bars_by_day, slope_window=3, flat_epsilon=0.10,
        label_horizon=3, atr_multiple=0.50,
    )
    feature_lookup = {
        (str(row["session_date"]), str(row["timestamp"])[11:16]): row
        for row in features
    }
    sessions = sorted(bars_by_day)
    trades, _ = alignment.replay(
        cache_root=cache_root,
        all_sessions=sessions,
        analysis_sessions=[day],
        feature_lookup=feature_lookup,
        flat_epsilon=0.10,
        strategy_cutoff_only=True,
    )
    trades = [row for row in trades if row["session_date"] == day]
    if not trades:
        raise ValueError(f"canonical replay produced no completed trades: {day}")
    states, snapshots, minutes = delayed.build_indicator_states(
        cache_root, {day}, strategy_cutoff_only=True
    )
    results: list[dict] = []
    attempts: list[dict] = []
    timeline: list[dict] = []
    for trade in trades:
        first_touch, trace = delayed.validate_trade(
            trade,
            states=states,
            snapshots=snapshots,
            candles=minutes[day],
            threshold=0.75,
            strong_threshold=1.0,
            timeout_minutes=10,
        )
        confirmed, trade_attempts = backtest.ordered_gap_confirmation(trace, 0.75)
        attempts.extend(trade_attempts)
        timeline.extend(trace)
        canonical = float(trade["captured_points"])
        candidate_price = None if confirmed is None else float(confirmed["confirmation_close"])
        candidate_points = None if confirmed is None else backtest.directional_points(
            trade["direction"], candidate_price, float(trade["exit_price"])
        )
        results.append({
            **trade,
            "evidence_block": "NEW_FORWARD_CONFIRMATION",
            "canonical_points": canonical,
            "canonical_reached_plus20": float(trade["mfe_points"]) >= 20.0,
            "first_touch_decision": first_touch["candidate_decision"],
            "first_touch_timestamp": first_touch["first_wma_075_timestamp"],
            "first_touch_points": first_touch.get("delayed_entry_to_canonical_exit_points"),
            "candidate_decision": "ENTRY" if confirmed else "NO_ENTRY",
            "candidate_entry_timestamp": None if confirmed is None else confirmed["confirmation_timestamp"],
            "candidate_entry_price": candidate_price,
            "candidate_points": candidate_points,
            "candidate_delta_vs_canonical": None if candidate_points is None else candidate_points - canonical,
            "attempt_count": len(trade_attempts),
        })
    return results, attempts, timeline


def publish_session(day: str, cache_root: Path, output_root: Path, evidence_root: Path = DEFAULT_EVIDENCE) -> dict[str, Any]:
    sessions_root = output_root / "sessions"
    target = sessions_root / day
    if (target / "manifest.json").is_file():
        return {"session_date": day, "status": "ALREADY_PUBLISHED"}
    cache = ensure_recorded_cache(day, cache_root, evidence_root)
    results, attempts, timeline = generate_session(day, cache_root)
    temporary = sessions_root / f".{day}.tmp-{os.getpid()}"
    if temporary.exists():
        shutil.rmtree(temporary)
    temporary.mkdir(parents=True)
    write_csv(temporary / FILES[0], results)
    write_csv(temporary / FILES[1], attempts)
    write_csv(temporary / FILES[2], timeline)
    manifest = {
        "model": "HILEGA_WMA_GAP_FORWARD_SESSION_V1",
        "session_date": day,
        "published_at": datetime.now(IST).isoformat(),
        "signals": len(results),
        "candidate_entries": sum(row["candidate_decision"] == "ENTRY" for row in results),
        "candidate_denied": sum(row["candidate_decision"] == "NO_ENTRY" for row in results),
        "canonical_points": sum(float(row["canonical_points"]) for row in results),
        "candidate_points": sum(float(row["candidate_points"]) for row in results if row["candidate_points"] is not None),
        "frozen_parent": str(FROZEN_ROOT),
        "frozen_trade_results_sha256": file_sha256(FROZEN_ROOT / "trade-results.csv"),
        "observation_only": True,
        "execution_enabled": False,
        "cache_materialization": cache,
    }
    (temporary / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    target.parent.mkdir(parents=True, exist_ok=True)
    os.replace(temporary, target)
    return {"session_date": day, "status": "PUBLISHED", **manifest}


def rebuild_indexes(output_root: Path) -> dict[str, Any]:
    manifests = []
    collected = {name: [] for name in FILES}
    sessions_root = output_root / "sessions"
    if sessions_root.is_dir():
        for child in sorted(sessions_root.iterdir()):
            manifest = child / "manifest.json"
            if not manifest.is_file():
                continue
            manifests.append(json.loads(manifest.read_text()))
            for name in FILES:
                collected[name].extend(csv_rows(child / name))
    output_root.mkdir(parents=True, exist_ok=True)
    for name, rows in collected.items():
        write_csv(output_root / name, rows)
    report = {
        "model": "HILEGA_WMA_GAP_FORWARD_CONFIRMATION_V1",
        "frozen_parent": str(FROZEN_ROOT),
        "frozen_trade_results_sha256": file_sha256(FROZEN_ROOT / "trade-results.csv"),
        "forward_sessions": len(manifests),
        "selected_dates": [row["session_date"] for row in manifests],
        "signals": sum(int(row["signals"]) for row in manifests),
        "canonical_points": sum(float(row["canonical_points"]) for row in manifests),
        "candidate_points": sum(float(row["candidate_points"]) for row in manifests),
        "session_manifests": manifests,
        "rule_locked": {
            "signal": "UNCHANGED_CANONICAL_HILEGA_DIRECTIONAL_SIGNAL",
            "wma_arm": "DIRECTIONAL_WMA21_CHANGE_GE_0_75",
            "confirmation": "LATER_CONSECUTIVE_1M_POSITIVE_EXPANDING_DIRECTIONAL_EMA3_WMA21_GAP",
            "timeout_minutes": 10,
            "exit": "UNCHANGED_CANONICAL_EXIT",
        },
        "observation_only": True,
        "execution_enabled": False,
        "updated_at": datetime.now(IST).isoformat(),
    }
    temporary = output_root / "report.json.tmp"
    temporary.write_text(json.dumps(report, indent=2) + "\n")
    os.replace(temporary, output_root / "report.json")
    return report


def run_once(audit_path: Path, cache_root: Path, output_root: Path, evidence_root: Path = DEFAULT_EVIDENCE) -> dict[str, Any]:
    frozen = frozen_dates(FROZEN_ROOT)
    frozen_cutoff = frozen_last_session(FROZEN_ROOT)
    completed = completed_live_sessions(audit_path)
    existing = {
        child.name for child in (output_root / "sessions").glob("????-??-??")
        if (child / "manifest.json").is_file()
    }
    pending = [
        day for day in completed
        if day not in existing and day not in frozen
        and (frozen_cutoff is None or day > frozen_cutoff)
    ]
    published, waiting = [], []
    for day in pending:
        try:
            published.append(publish_session(day, cache_root, output_root, evidence_root))
        except ValueError as exc:
            waiting.append({"session_date": day, "reason": str(exc)})
    report = rebuild_indexes(output_root)
    return {
        "status": "PUBLISHED" if published else "NOOP",
        "completed_live_sessions": len(completed),
        "frozen_sessions_untouched": len(frozen),
        "frozen_last_session": frozen_cutoff,
        "published": published,
        "waiting_for_complete_cache": waiting,
        "forward_sessions": report["forward_sessions"],
        "observation_only": True,
        "execution_enabled": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--serve", action="store_true")
    parser.add_argument("--interval-seconds", type=int, default=900)
    parser.add_argument("--audit", type=Path, default=DEFAULT_AUDIT)
    parser.add_argument("--cache-root", type=Path, default=DEFAULT_CACHE)
    parser.add_argument("--output-root", type=Path, default=OUTPUT_ROOT)
    parser.add_argument("--evidence-root", type=Path, default=DEFAULT_EVIDENCE)
    args = parser.parse_args()
    if args.once == args.serve:
        raise SystemExit("choose exactly one of --once or --serve")
    if not 60 <= args.interval_seconds <= 86400:
        raise SystemExit("interval must be between 60 and 86400 seconds")
    try:
        with FileLock(str(LOCK), timeout=0):
            while True:
                result = run_once(args.audit, args.cache_root, args.output_root, args.evidence_root)
                print(json.dumps(result, sort_keys=True), flush=True)
                if args.once:
                    return 0
                time.sleep(args.interval_seconds)
    except Timeout:
        print("NOOP: another Hilega WMA-gap forward publisher owns the lock")
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
