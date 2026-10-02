#!/usr/bin/env python3
"""Compare current and health-confirmed exits over the fixed 490 sessions.

Family A is replayed as a parallel observation lane.  The canonical B/E,
B_REARM and PM B/E lane remains authoritative and unchanged.  All valuations
use completed NIFTY one-minute closes; no order or quantity is created.
"""

from __future__ import annotations

import argparse
import csv
import importlib.util
import json
import statistics
import tempfile
import os
from collections import defaultdict
from datetime import datetime
from pathlib import Path

from market_lab.midpoint_strategy.config import MidpointShadowConfig
from market_lab.midpoint_strategy.live_shadow_v1 import (
    MidpointLiveShadowCoordinatorV1,
)
from market_lab.domain import IST


GOOD_BAD = Path("scripts/research_midpoint_good_bad_features.py")
CURRENT = Path("scripts/backtest_midpoint_current_strategy.py")
PM = Path("scripts/backtest_midpoint_pm_be.py")
DEFAULT_FORWARD_ROOT = Path(
    "data/historical-evidence/hilega-pcr-oi-support-research-v1/"
    "midpoint-forward-oos-2026-09-09-to-29-v2"
)
DEFAULT_OUTPUT = Path(
    "data/historical-evidence/hilega-pcr-oi-support-research-v1/"
    "midpoint-a-continuous-health-490-v1"
)
DEFAULT_LIVE_AUDIT = Path(
    "data/live-observation/midpoint-strategy-v1/audit.jsonl"
)

ENTRY_TYPES = {
    "A_ENTRY", "B_ENTRY", "E_ENTRY", "B_REARM_ENTRY", "E_REARM_ENTRY",
    "PM_B_ENTRY", "PM_E_ENTRY",
}
POLICIES = (
    "CURRENT_EXIT_POLICY",
    "HEALTH_IMMEDIATE_CONFIRMATION",
    "HEALTH_TWO_CLOSE_CONFIRMATION",
)


class DummySources:
    pass


def research_config() -> MidpointShadowConfig:
    return MidpointShadowConfig(
        family_a_enabled=True, family_b_enabled=True, family_e_enabled=True,
        family_c_enabled=False, be_rearm_enabled=True,
        family_d_enabled=False, pm_e_enabled=True,
        normal_b_proved_candidate_enabled=True,
        degraded_exit_candidate_enabled=True,
        continuous_health_exit_candidate_enabled=True,
        post_rescue_reentry_enabled=False,
    )


def load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def dt(value: str) -> datetime:
    return datetime.fromisoformat(value)


def load_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text().splitlines() if line]


def replay_session(day: str, underlying: dict, futures: dict, current) -> list[dict]:
    config = research_config()
    config.assert_safe()
    with tempfile.TemporaryDirectory(prefix="midpoint-a-health-") as temp:
        audit_path = Path(temp) / "audit.jsonl"
        coordinator = MidpointLiveShadowCoordinatorV1(
            market_sources=DummySources(), audit_path=audit_path, config=config
        )
        coordinator._reset_session(dt(day + "T09:15:00+05:30").date())
        underlying_by_ts = {
            dt(timestamp): current.candle(timestamp, row)
            for timestamp, row in underlying.items()
        }
        for timestamp in sorted(set(underlying).intersection(futures), key=dt):
            moment = dt(timestamp)
            if moment.strftime("%H:%M") < "09:15":
                continue
            future = futures[timestamp]
            coordinator._process_minute(
                ts=moment,
                underlying=underlying_by_ts[moment],
                futures_close=float(future["close"]),
                futures_vwap=float(future["vwap"]),
                underlying_by_ts=underlying_by_ts,
                futures_open=float(future.get("open", future["close"])),
                futures_volume=float(future.get("volume", 0.0) or 0.0),
            )
        return load_jsonl(audit_path)


def replay_today_from_broker(day: str) -> tuple[list[dict], dict]:
    """Replay today's available completed minutes into a temporary audit."""
    from dotenv import load_dotenv
    from market_lab.upstox_live_shadow_sources_v1 import UpstoxLiveShadowSourcesV1

    now = datetime.now(IST)
    if day != now.date().isoformat():
        raise ValueError("broker intraday replay is available only for today's date")
    load_dotenv(".env")
    token = os.getenv("UPSTOX_ACCESS_TOKEN", "")
    if not token:
        raise ValueError("UPSTOX_ACCESS_TOKEN is unavailable")
    source = UpstoxLiveShadowSourcesV1(token)
    try:
        with tempfile.TemporaryDirectory(prefix="midpoint-a-health-live-") as temp:
            audit_path = Path(temp) / "audit.jsonl"
            coordinator = MidpointLiveShadowCoordinatorV1(
                market_sources=source, audit_path=audit_path,
                config=research_config(),
            )
            coordinator.process(now)
            audit = load_jsonl(audit_path)
            candles = source.nifty_intraday_1m(now=now)
            underlying = {
                candle.timestamp.astimezone(IST).replace(
                    second=0, microsecond=0
                ).isoformat(): {
                    "open": float(candle.open), "high": float(candle.high),
                    "low": float(candle.low), "close": float(candle.close),
                    "volume": float(getattr(candle, "volume", 0.0) or 0.0),
                }
                for candle in candles
                if candle.timestamp.astimezone(IST).date() == now.date()
            }
            return audit, underlying
    finally:
        source.close()


def entry_kind(entry: dict) -> str:
    event_type = str(entry["event_type"])
    if event_type.endswith("_REARM_ENTRY"):
        return event_type.removesuffix("_ENTRY")
    return str(entry.get("family") or event_type.removesuffix("_ENTRY"))


def same_lane(row: dict, entry: dict) -> bool:
    return (
        row.get("family") == entry.get("family")
        and row.get("reference_type") == entry.get("reference_type")
    )


def current_exit(segment: list[dict]) -> dict | None:
    route = next((r for r in segment
                  if r.get("event_type") == "MANAGEMENT_ROUTE_SELECTED"), None)
    route_name = route.get("result") if route else None
    if route_name == "NORMAL_B_PROVED_THREE_TIER":
        found = next((r for r in segment
                      if r.get("event_type") ==
                      "NORMAL_B_PROVED_EXIT_CANDIDATE"), None)
        if found is not None:
            return found
    if route_name == "RUNNER_DEGRADED_EXIT":
        found = next((r for r in segment
                      if r.get("event_type") ==
                      "DEGRADED_EXIT_CANDIDATE_TRIGGERED"), None)
        if found is not None:
            return found
    return next((r for r in segment
                 if r.get("event_type") == "STRUCTURAL_TERMINAL"), None)


def policy_exit(segment: list[dict], policy: str) -> dict | None:
    if policy == "CURRENT_EXIT_POLICY":
        return current_exit(segment)
    return next((r for r in segment if r.get("event_type") ==
                 f"{policy}_EXIT_CANDIDATE"), None)


def directional_points(direction: str, entry: float, price: float) -> float:
    return price - entry if direction == "BULLISH" else entry - price


def mfe_until(underlying: dict, entry: dict, exit_event: dict | None) -> float | None:
    if exit_event is None:
        return None
    start, end = entry["event_timestamp"], exit_event["event_timestamp"]
    rows = [row for timestamp, row in underlying.items() if start <= timestamp <= end]
    if not rows:
        return None
    price = float(entry["underlying_price"])
    if entry["direction"] == "BULLISH":
        return max(float(row["high"]) - price for row in rows)
    return max(price - float(row["low"]) for row in rows)


def reconstruct(day: str, block: str, rows: list[dict], underlying: dict) -> list[dict]:
    trades: list[dict] = []
    entries = [(i, row) for i, row in enumerate(rows)
               if row.get("event_type") in ENTRY_TYPES]
    for index, entry in entries:
        stop = len(rows)
        for later_index, later in enumerate(rows[index + 1:], start=index + 1):
            if same_lane(later, entry) and later.get("event_type") == "STRUCTURAL_TERMINAL":
                stop = later_index + 1
                break
            if (later.get("event_type") in ENTRY_TYPES and same_lane(later, entry)):
                stop = later_index
                break
        segment = [row for row in rows[index:stop] if same_lane(row, entry)]
        control = policy_exit(segment, "CURRENT_EXIT_POLICY")
        control_points = (
            float(control["directional_points"])
            if control is not None and control.get("directional_points") is not None
            else None
        )
        for policy in POLICIES:
            exit_event = policy_exit(segment, policy)
            price = (
                float(exit_event["underlying_price"])
                if exit_event is not None and exit_event.get("underlying_price") is not None
                else None
            )
            points = (
                float(exit_event["directional_points"])
                if exit_event is not None and exit_event.get("directional_points") is not None
                else directional_points(
                    entry["direction"], float(entry["underlying_price"]), price
                ) if price is not None else None
            )
            mfe = mfe_until(underlying, entry, exit_event)
            evidence = (exit_event or {}).get("evidence") or {}
            trades.append({
                "block": block,
                "session_date": day,
                "entry_kind": entry_kind(entry),
                "family": entry.get("family"),
                "direction": entry.get("direction"),
                "entry_timestamp": entry.get("event_timestamp"),
                "entry_price": entry.get("underlying_price"),
                "policy": policy,
                "exit_timestamp": (exit_event or {}).get("event_timestamp"),
                "exit_event": (exit_event or {}).get("event_type"),
                "exit_reason": (exit_event or {}).get("reason"),
                "exit_points": points,
                "mfe_to_exit": mfe,
                "giveback_from_mfe": mfe - points
                    if mfe is not None and points is not None else None,
                "delta_vs_current": points - control_points
                    if points is not None and control_points is not None else None,
                "health_at_exit": evidence.get("health"),
                "armed_reason": evidence.get("armed_reason"),
                "status": "CLOSED" if exit_event is not None else "UNRESOLVED",
                "observation_only": True,
                "execution_enabled": False,
                "paper_order_enabled": False,
                "quantity": None,
                "order_sent": False,
            })
    return trades


def metrics(rows: list[dict]) -> dict:
    values = [float(row["exit_points"]) for row in rows
              if row.get("exit_points") is not None]
    givebacks = [float(row["giveback_from_mfe"]) for row in rows
                 if row.get("giveback_from_mfe") is not None]
    return {
        "entries": len(rows),
        "completed": len(values),
        "unresolved": len(rows) - len(values),
        "sum_points": round(sum(values), 6),
        "mean_points": round(statistics.mean(values), 6) if values else None,
        "median_points": round(statistics.median(values), 6) if values else None,
        "positive": sum(value > 0 for value in values),
        "negative": sum(value < 0 for value in values),
        "win_rate_pct": round(100 * sum(v > 0 for v in values) / len(values), 6)
            if values else None,
        "mean_giveback_from_mfe": round(statistics.mean(givebacks), 6)
            if givebacks else None,
    }


def write_csv(path: Path, rows: list[dict]) -> None:
    if not rows:
        path.write_text("")
        return
    with path.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def summarize_live(path: Path, day: str) -> dict:
    rows = [row for row in load_jsonl(path) if row.get("session_date") == day]
    entries = [row for row in rows if row.get("event_type") in ENTRY_TYPES]
    return {
        "session_date": day,
        "event_count": len(rows),
        "entry_count": len(entries),
        "entries": [{
            "event_type": row.get("event_type"),
            "family": row.get("family"),
            "direction": row.get("direction"),
            "timestamp": row.get("event_timestamp"),
        } for row in entries],
        "continuous_health_checks": sum(
            row.get("event_type") == "CONTINUOUS_HEALTH_CHECK" for row in rows
        ),
        "health_immediate_exits": sum(
            row.get("event_type") ==
            "HEALTH_IMMEDIATE_CONFIRMATION_EXIT_CANDIDATE" for row in rows
        ),
        "health_two_close_exits": sum(
            row.get("event_type") ==
            "HEALTH_TWO_CLOSE_CONFIRMATION_EXIT_CANDIDATE" for row in rows
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--forward-root", type=Path, default=DEFAULT_FORWARD_ROOT)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--live-audit", type=Path, default=DEFAULT_LIVE_AUDIT)
    parser.add_argument("--live-session-date", default="2026-10-01")
    parser.add_argument(
        "--skip-today-broker-replay", action="store_true",
        help="Use only the immutable live-audit summary; do not fetch today",
    )
    args = parser.parse_args()

    current = load_module(CURRENT, "current_for_a_health_490")
    pm = load_module(PM, "pm_for_a_health_490")
    good = load_module(GOOD_BAD, "good_for_a_health_490")
    v55 = current.import_module(current.V55, "v55_for_a_health_490")
    v52 = current.import_module(current.V52, "v52_for_a_health_490")
    canon = current.import_module(current.CANON, "canon_for_a_health_490")

    sessions: dict[str, dict] = {}
    for block in v52.BLOCKS:
        underlying, futures, _ = v55.load_block(block, v52, canon)
        for day in sorted(set(underlying).intersection(futures)):
            sessions[day] = {
                "block": block["name"], "underlying": underlying[day],
                "futures": futures[day], "source": "FROZEN_480",
            }
    frozen = sorted(sessions)
    if len(frozen) != 480:
        raise SystemExit(f"STOP: expected 480 frozen sessions, found {len(frozen)}")
    forward = pm.load_forward_sessions(args.forward_root)
    if len(forward) != 14:
        raise SystemExit(f"STOP: expected 14 forward sessions, found {len(forward)}")
    selected_forward = sorted(forward)[-10:]
    for day in selected_forward:
        underlying, futures = forward[day]
        sessions[day] = {
            "block": "FORWARD_LATEST_10", "underlying": underlying,
            "futures": futures, "source": "FORWARD_LATEST_10",
        }
    analysis_dates = frozen + selected_forward
    if len(set(analysis_dates)) != 490:
        raise SystemExit("STOP: fixed analysis universe is not exactly 490 sessions")

    all_rows: list[dict] = []
    for count, day in enumerate(analysis_dates, start=1):
        market = sessions[day]
        audit = replay_session(day, market["underlying"], market["futures"], current)
        all_rows.extend(reconstruct(
            day, market["block"], audit, market["underlying"]
        ))
        if count % 50 == 0:
            print(f"Processed {count}/490 sessions", flush=True)

    summary = {policy: metrics([r for r in all_rows if r["policy"] == policy])
               for policy in POLICIES}
    by_family: dict[str, dict] = defaultdict(dict)
    for family in sorted({str(row["entry_kind"]) for row in all_rows}):
        for policy in POLICIES:
            by_family[family][policy] = metrics([
                row for row in all_rows
                if row["entry_kind"] == family and row["policy"] == policy
            ])
    today_rows: list[dict] = []
    today_replay_error = None
    if not args.skip_today_broker_replay:
        try:
            today_audit, today_underlying = replay_today_from_broker(
                args.live_session_date
            )
            today_rows = reconstruct(
                args.live_session_date, "TODAY_BROKER_INTRADAY_REPLAY",
                today_audit, today_underlying,
            )
        except Exception as exc:  # audit summary remains available and explicit
            today_replay_error = f"{type(exc).__name__}: {exc}"

    report = {
        "model": "MIDPOINT_A_CONTINUOUS_HEALTH_490_V1",
        "sessions": 490,
        "frozen_sessions": 480,
        "forward_sessions": selected_forward,
        "policies": summary,
        "by_entry_kind": by_family,
        "today_live_audit": summarize_live(
            args.live_audit, args.live_session_date
        ),
        "today_broker_replay": {
            "status": "AVAILABLE" if today_rows else "UNAVAILABLE",
            "error": today_replay_error,
            "policies": {
                policy: metrics([r for r in today_rows if r["policy"] == policy])
                for policy in POLICIES
            },
        },
        "guardrails": {
            "a_parallel_non_blocking": True,
            "current_exit_policy_unchanged": True,
            "health_uses_completed_one_minute_closes": True,
            "future_leakage_allowed": False,
        },
        "safety": {
            "observation_only": True, "execution_enabled": False,
            "paper_order_enabled": False, "quantity": None,
            "order_sent": False,
        },
    }
    args.output_dir.mkdir(parents=True, exist_ok=True)
    write_csv(args.output_dir / "trade-policy-comparison.csv", all_rows)
    write_csv(args.output_dir / "today-trade-policy-comparison.csv", today_rows)
    (args.output_dir / "report.json").write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n"
    )
    print("Sessions: 490 policy rows:", len(all_rows))
    for policy, result in summary.items():
        print(policy, result)
    print("Today live audit:", report["today_live_audit"])
    print("Today broker replay:", report["today_broker_replay"])
    print("Output:", args.output_dir / "report.json")
    print("Observation only: no service, audit, order or quantity modified.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
