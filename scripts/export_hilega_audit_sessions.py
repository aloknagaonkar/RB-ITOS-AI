#!/usr/bin/env python3
"""Export read-only per-candle Hilega audit reports from the running local API."""

from __future__ import annotations

import argparse
import csv
import json
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import urlopen


FIELDS = [
    "timestamp", "source", "directional_mode", "evidence_level", "open", "high", "low", "close",
    "rsi", "ema", "wma", "previous_rsi", "previous_ema", "previous_wma",
    "ema_minus_wma", "wma21_slope_change", "wma21_slope_direction",
    "wma21_slope_required", "wma21_slope_gate_status", "wma21_slope_pass",
    "wma21_current_candle", "wma21_previous_candle", "wma21_slope_interval_minutes",
    "bullish_wma21_rising", "bearish_wma21_falling", "market_direction",
    "directional_action", "events_emitted",
]


def get_json(url: str) -> dict:
    with urlopen(url, timeout=60) as response:
        return json.load(response)


def minute_key(value) -> str | None:
    if not value:
        return None
    text = str(value)
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return str(int(parsed.timestamp() // 60))
    except ValueError:
        return text[:16]


def number(value):
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def directional_direction(row: dict) -> str | None:
    action = str(row.get("action") or "").upper()
    events = str(row.get("accepted_events") or "").upper()
    if "BEARISH" in events:
        return "BEARISH"
    if "PATH1_ARMED_RSI_CROSS_EMA3_UP" in events:
        return "BULLISH"
    if action == "ARMED_INFORMATION":
        if row.get("bearish_armed") is True:
            return "BEARISH"
        if row.get("bullish_armed") is True:
            return "BULLISH"
    if action.startswith("BEARISH_"):
        return "BEARISH"
    if action.startswith("BULLISH_"):
        return "BULLISH"
    if row.get("bearish_armed") is True and row.get("bullish_armed") is not True:
        return "BEARISH"
    if row.get("bullish_armed") is True and row.get("bearish_armed") is not True:
        return "BULLISH"
    for key in ("owner_after", "owner_before"):
        if row.get(key) in ("BULLISH", "BEARISH"):
            return row[key]
    if "BEARISH_ACTIVE" in str(row.get("bearish_state") or ""):
        return "BEARISH"
    if "BULLISH_ACTIVE" in str(row.get("bullish_state") or ""):
        return "BULLISH"
    return None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:8123")
    parser.add_argument("--dates", nargs="+", help="Trading dates in YYYY-MM-DD form")
    parser.add_argument("--all-sessions", action="store_true", help="Export every date listed by the historical UI")
    parser.add_argument("--output", type=Path, default=Path("hilega-audit-export.csv"))
    args = parser.parse_args()
    if bool(args.dates) == args.all_sessions:
        parser.error("provide --dates YYYY-MM-DD [...] or --all-sessions")

    base = args.base_url.rstrip("/")
    try:
        if args.all_sessions:
            index = get_json(f"{base}/api/live-shadow/hilega-historical/sessions")
            dates = [x["session_date"] for x in index.get("sessions", [])]
        else:
            dates = args.dates

        rows, sessions, errors = [], [], []
        for day in dates:
            url = f"{base}/api/live-shadow/hilega-historical/session?{urlencode({'session_date': day})}"
            try:
                session = get_json(url)
            except (HTTPError, URLError, TimeoutError, ValueError) as exc:
                errors.append({"session_date": day, "error": str(exc)})
                continue
            reports = session.get("reports") or []
            directional = {}
            directional_error = None
            directional_url = (
                f"{base}/api/live-shadow/hilega-directional-candles/historical?"
                f"{urlencode({'session_date': day})}"
            )
            try:
                directional = get_json(directional_url)
            except (HTTPError, URLError, TimeoutError, ValueError) as exc:
                # The UI also keeps the base audit if a date has no candle overlay.
                directional_error = str(exc)
            candle_rows = directional.get("rows") or []
            report_by_minute = {
                minute_key(report.get("checkpoint")): report
                for report in reports
                if minute_key(report.get("checkpoint"))
            }
            prior_by_minute = {}
            previous = None
            for candle in sorted(candle_rows, key=lambda item: str(item.get("bar_timestamp") or "")):
                stamp = str(candle.get("bar_timestamp") or "")
                key = minute_key(stamp)
                if key and previous and str(previous.get("bar_timestamp") or "")[:10] == stamp[:10]:
                    prior_by_minute[key] = previous
                previous = candle

            sessions.append({
                "session_date": day,
                "source": session.get("source"),
                "evidence_level": session.get("evidence_level"),
                "report_count": len(reports),
                "directional_mode": directional.get("mode"),
                "directional_row_count": len(candle_rows),
                "directional_error": directional_error,
            })
            output_items = []
            used_reports = set()
            for candle in candle_rows:
                key = minute_key(candle.get("bar_timestamp"))
                report = report_by_minute.get(key)
                if report is not None:
                    used_reports.add(key)
                output_items.append((report or {}, candle))
            for report in reports:
                key = minute_key(report.get("checkpoint"))
                if key not in used_reports:
                    output_items.append((report, {}))

            for report, candle in output_items:
                bar = report.get("bar") or {}
                indicators = report.get("indicators") or {}
                conditions = report.get("conditions") or {}
                strategy = report.get("strategy") or {}
                prior = prior_by_minute.get(minute_key(candle.get("bar_timestamp"))) or {}
                ema = candle.get("ema3_rsi", indicators.get("ema3_rsi"))
                wma = candle.get("wma21_rsi", indicators.get("wma21_rsi"))
                rsi = candle.get("rsi9", indicators.get("rsi9"))
                previous_rsi = prior.get("rsi9", indicators.get("previous_rsi9"))
                previous_ema = prior.get("ema3_rsi", indicators.get("previous_ema3_rsi"))
                previous_wma = candle.get("previous_wma21_rsi", prior.get("wma21_rsi", indicators.get("previous_wma21_rsi")))
                slope_change = candle.get("wma21_slope_change", conditions.get("wma21_slope_change"))
                if slope_change is None and number(wma) is not None and number(previous_wma) is not None:
                    slope_change = number(wma) - number(previous_wma)
                direction = directional_direction(candle) if candle else strategy.get("direction")
                slope_required = candle.get("wma21_slope_required", conditions.get("wma21_slope_required"))
                slope_pass = None
                if slope_change is not None and direction in ("BULLISH", "BEARISH"):
                    slope_pass = number(slope_change) > 0 if direction == "BULLISH" else number(slope_change) < 0
                if not slope_required:
                    slope_status = "INFORMATIONAL_ONLY"
                elif slope_pass is None:
                    slope_status = "UNAVAILABLE"
                else:
                    slope_status = "PASS" if slope_pass else "FAIL"
                emitted = candle.get("accepted_events", strategy.get("events_emitted")) or []
                emitted_text = emitted if isinstance(emitted, str) else "|".join(map(str, emitted))
                try:
                    gap = float(ema) - float(wma) if ema is not None and wma is not None else None
                except (TypeError, ValueError):
                    gap = None
                rows.append({
                    "timestamp": candle.get("bar_timestamp", report.get("checkpoint")),
                    "source": session.get("source"),
                    "directional_mode": directional.get("mode"),
                    "evidence_level": session.get("evidence_level"),
                    "open": candle.get("open", bar.get("open")), "high": candle.get("high", bar.get("high")),
                    "low": candle.get("low", bar.get("low")), "close": candle.get("close", bar.get("close")),
                    "rsi": rsi, "ema": ema, "wma": wma,
                    "previous_rsi": previous_rsi,
                    "previous_ema": previous_ema,
                    "previous_wma": previous_wma,
                    "ema_minus_wma": gap,
                    "wma21_slope_change": slope_change,
                    "wma21_slope_direction": candle.get("wma21_slope_direction", conditions.get("wma21_slope_direction")) or ("RISING" if number(slope_change) is not None and number(slope_change) > 0 else "FALLING" if number(slope_change) is not None and number(slope_change) < 0 else "FLAT" if number(slope_change) == 0 else "UNAVAILABLE"),
                    "wma21_slope_required": slope_required,
                    "wma21_slope_gate_status": slope_status,
                    "wma21_slope_pass": slope_pass if slope_required else None,
                    "wma21_current_candle": candle.get("bar_timestamp", conditions.get("wma21_current_candle")),
                    "wma21_previous_candle": candle.get("wma21_previous_candle", prior.get("bar_timestamp", conditions.get("wma21_previous_candle"))),
                    "wma21_slope_interval_minutes": candle.get("wma21_slope_interval_minutes", conditions.get("wma21_slope_interval_minutes")),
                    "bullish_wma21_rising": number(slope_change) > 0 if number(slope_change) is not None else None,
                    "bearish_wma21_falling": number(slope_change) < 0 if number(slope_change) is not None else None,
                    "market_direction": direction,
                    "directional_action": candle.get("action", strategy.get("directional_action")),
                    "events_emitted": emitted_text,
                })
    except (HTTPError, URLError, TimeoutError, ValueError, KeyError) as exc:
        parser.error(f"Could not read the historical API: {exc}")

    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(rows)
    print(json.dumps({
        "output": str(args.output),
        "dates_requested": len(dates),
        "dates_exported": len(sessions),
        "rows_exported": len(rows),
        "sessions": sessions,
        "errors": errors,
        "note": "Read-only API export; no broker calls or replay mutation.",
    }, indent=2))
    return 0 if rows and not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
