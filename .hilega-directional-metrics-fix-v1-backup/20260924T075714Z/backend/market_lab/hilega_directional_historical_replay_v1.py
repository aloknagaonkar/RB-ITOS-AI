from __future__ import annotations

import csv
import json
from dataclasses import asdict, dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Sequence

from .hilega_directional_coordinator_v1 import (
    BULLISH_ENTRY_EVENTS,
    BULLISH_EXIT_EVENTS,
    BEARISH_ENTRY_EVENTS,
    BEARISH_EXIT_EVENTS,
    DirectionalDecision,
    HilegaDirectionalCoordinatorV1,
)
from .hilega_milega_historical_replay_v1 import (
    HistoricalUnderlyingGateway,
    UNDERLYING,
    aggregate_exact_5m,
    load_or_fetch_1m,
)

MODEL = "HILEGA_DIRECTIONAL_HISTORICAL_REPLAY_V1"


@dataclass(frozen=True)
class DirectionalTradeRow:
    session_date: str
    direction: str
    entry_time: str
    entry_event: str
    entry_price: float
    exit_time: str
    exit_event: str
    exit_price: float
    points: float
    outcome: str
    holding_minutes: int


@dataclass(frozen=True)
class DirectionalSessionSummary:
    session_date: str
    status: str
    bars_5m: int
    directional_trades: int
    bullish_trades: int
    bearish_trades: int
    positive: int
    negative: int
    flat: int
    net_directional_points: float
    bullish_points: float
    bearish_points: float
    suppressed_bullish_entries: int
    suppressed_bearish_entries: int
    bullish_armed_while_bearish_active: int
    bearish_armed_while_bullish_active: int
    same_candle_reversal_blocks: int
    errors: str | None = None


def _write_csv(path: Path, rows: Sequence[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    fields: list[str] = []
    seen: set[str] = set()
    for row in rows:
        for key in row:
            if key not in seen:
                fields.append(key)
                seen.add(key)
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)


def _event_types(events) -> list[str]:
    return [e.event_type for e in events]


def _accepted_entry(decision: DirectionalDecision) -> tuple[str, Any] | None:
    for e in decision.accepted_events:
        if e.event_type in BULLISH_ENTRY_EVENTS:
            return "BULLISH", e
        if e.event_type in BEARISH_ENTRY_EVENTS:
            return "BEARISH", e
    return None


def _accepted_exit(decision: DirectionalDecision, direction: str) -> Any | None:
    allowed = BULLISH_EXIT_EVENTS if direction == "BULLISH" else BEARISH_EXIT_EVENTS
    for e in decision.accepted_events:
        if e.event_type in allowed:
            return e
    return None


def _directional_points(direction: str, entry: float, exit_: float) -> float:
    return (exit_ - entry) if direction == "BULLISH" else (entry - exit_)


def _pair_trade(
    *,
    active: dict[str, Any],
    exit_event: Any,
) -> DirectionalTradeRow:
    entry_dt = active["entry_dt"]
    exit_dt = exit_event.event_time
    entry_price = float(active["entry_price"])
    exit_price = float(exit_event.price)
    pts = _directional_points(active["direction"], entry_price, exit_price)
    return DirectionalTradeRow(
        session_date=entry_dt.date().isoformat(),
        direction=active["direction"],
        entry_time=entry_dt.strftime("%H:%M"),
        entry_event=active["entry_event"],
        entry_price=entry_price,
        exit_time=exit_dt.strftime("%H:%M"),
        exit_event=exit_event.event_type,
        exit_price=exit_price,
        points=pts,
        outcome="POSITIVE" if pts > 0 else ("NEGATIVE" if pts < 0 else "FLAT"),
        holding_minutes=int((exit_dt - entry_dt).total_seconds() // 60),
    )


def _row_from_decision(bar, decision: DirectionalDecision, coordinator: HilegaDirectionalCoordinatorV1) -> dict[str, Any]:
    ind = coordinator.bullish.previous_indicators
    accepted = _event_types(decision.accepted_events)
    suppressed = _event_types(decision.suppressed_events)

    action = "NO_ACTION"
    if any(x in BULLISH_ENTRY_EVENTS for x in accepted):
        action = "BULLISH_ENTRY"
    elif any(x in BEARISH_ENTRY_EVENTS for x in accepted):
        action = "BEARISH_ENTRY"
    elif any(x in BULLISH_EXIT_EVENTS for x in accepted):
        action = "BULLISH_EXIT"
    elif any(x in BEARISH_EXIT_EVENTS for x in accepted):
        action = "BEARISH_EXIT"
    elif suppressed:
        action = "ENTRY_SUPPRESSED"
    elif decision.bullish_armed or decision.bearish_armed:
        action = "ARMED_INFORMATION"

    return {
        "session_date": bar.ts.date().isoformat(),
        "time": bar.ts.strftime("%H:%M"),
        "bar_timestamp": bar.ts.isoformat(),
        "open": bar.open,
        "high": bar.high,
        "low": bar.low,
        "close": bar.close,
        "volume": bar.volume,
        "rsi9": None if ind is None else ind.rsi9,
        "ema3_rsi": None if ind is None else ind.ema3_rsi,
        "wma21_rsi": None if ind is None else ind.wma21_rsi,
        "owner_before": decision.trade_owner_before,
        "owner_after": decision.trade_owner_after,
        "bullish_state": decision.bullish_state,
        "bearish_state": decision.bearish_state,
        "bullish_armed": decision.bullish_armed,
        "bearish_armed": decision.bearish_armed,
        "action": action,
        "accepted_events": ",".join(accepted),
        "suppressed_events": ",".join(suppressed),
        "note": decision.note,
    }


def _interesting(row: dict[str, Any]) -> bool:
    return (
        row["action"] != "NO_ACTION"
        or row["owner_before"] != row["owner_after"]
        or row["suppressed_events"]
        or (row["owner_after"] == "BULLISH" and row["bearish_armed"])
        or (row["owner_after"] == "BEARISH" and row["bullish_armed"])
        or row["time"] in {"09:15", "09:20", "09:25", "14:55"}
    )


def _write_manual_validation(
    path: Path,
    *,
    session_date: date,
    rows: Sequence[dict[str, Any]],
    trades: Sequence[DirectionalTradeRow],
) -> None:
    lines = [
        f"HILEGA DIRECTIONAL MANUAL VALIDATION — {session_date.isoformat()}",
        "=" * 132,
        "Combined bullish+bearish coordinator replay. No option selection and no live execution.",
        "",
        "TIME   CLOSE      RSI9    EMA3   WMA21  OWNER BEFORE -> AFTER    BULL STATE            BEAR STATE               ACTION",
        "-" * 132,
    ]
    def n(v: Any) -> str:
        return "NA" if v is None else f"{float(v):.2f}"
    for r in rows:
        lines.append(
            f"{r['time']:5} {n(r['close']):>9} {n(r['rsi9']):>7} {n(r['ema3_rsi']):>7} {n(r['wma21_rsi']):>7}  "
            f"{r['owner_before']:7} -> {r['owner_after']:7}  "
            f"{r['bullish_state'][:20]:20}  {r['bearish_state'][:22]:22}  {r['action']}"
        )
        if r["accepted_events"]:
            lines.append(f"      ACCEPTED:   {r['accepted_events']}")
        if r["suppressed_events"]:
            lines.append(f"      SUPPRESSED: {r['suppressed_events']}")
        if r["note"]:
            lines.append(f"      NOTE:       {r['note']}")
        if r["owner_after"] == "BULLISH" and r["bearish_armed"]:
            lines.append("      INFO:       BEARISH_ARMED while BULLISH_ACTIVE")
        if r["owner_after"] == "BEARISH" and r["bullish_armed"]:
            lines.append("      INFO:       BULLISH_ARMED while BEARISH_ACTIVE")

    lines.extend(["", "DIRECTIONAL TRADES", "-" * 132])
    if not trades:
        lines.append("No completed directional trades.")
    else:
        for t in trades:
            lines.append(
                f"{t.direction:7} {t.entry_time} {t.entry_price:.2f} -> "
                f"{t.exit_time} {t.exit_price:.2f} | {t.points:+.2f} pts | "
                f"{t.holding_minutes}m | {t.outcome} | {t.entry_event} -> {t.exit_event}"
            )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def replay_directional_sessions(
    *,
    gateway: HistoricalUnderlyingGateway,
    dates: Sequence[date],
    underlying: str = UNDERLYING,
    warmup_calendar_days: int = 45,
    cache_root: str | Path = "data/historical-evidence/hilega-milega-underlying-cache-v1",
    output_root: str | Path = "data/historical-evidence/hilega-directional-replay-v1",
    refresh_cache: bool = False,
) -> dict[str, Any]:
    if not dates:
        raise ValueError("at least one target date is required")

    targets = sorted(set(dates))
    target_set = set(targets)
    first, last = targets[0], targets[-1]
    begin = first - timedelta(days=warmup_calendar_days)
    out_root = Path(output_root)
    out_root.mkdir(parents=True, exist_ok=True)

    coordinator = HilegaDirectionalCoordinatorV1()
    session_summaries: list[DirectionalSessionSummary] = []
    all_trades: list[DirectionalTradeRow] = []
    all_interesting: list[dict[str, Any]] = []
    all_candles: list[dict[str, Any]] = []
    data_availability: dict[str, int] = {}

    current = begin
    while current <= last:
        candles = load_or_fetch_1m(
            gateway,
            underlying=underlying,
            session_date=current,
            cache_root=cache_root,
            refresh_cache=refresh_cache,
        )
        data_availability[current.isoformat()] = len(candles)

        if not candles:
            if current in target_set:
                session_summaries.append(
                    DirectionalSessionSummary(
                        current.isoformat(), "UNAVAILABLE", 0, 0, 0, 0, 0, 0, 0,
                        0.0, 0.0, 0.0, 0, 0, 0, 0, 0,
                        "No historical underlying candles returned.",
                    )
                )
            current += timedelta(days=1)
            continue

        bars = aggregate_exact_5m(candles, current)

        # Warm indicator histories only. Strategy comparisons and session states
        # must start fresh on the target session.
        if current not in target_set:
            for bar in bars:
                coordinator.bullish.indicators.update(bar.close)
                coordinator.bearish.indicators.update(bar.close)
            coordinator.bullish.previous_indicators = None
            coordinator.bullish.previous_bar = None
            coordinator.bearish.previous_indicators = None
            coordinator.bearish.previous_bar = None
            current += timedelta(days=1)
            continue

        session_dir = out_root/current.isoformat()
        session_dir.mkdir(parents=True, exist_ok=True)

        rows: list[dict[str, Any]] = []
        trades: list[DirectionalTradeRow] = []
        active: dict[str, Any] | None = None

        for bar in bars:
            decision = coordinator.on_bar(bar)
            row = _row_from_decision(bar, decision, coordinator)
            rows.append(row)

            entry = _accepted_entry(decision)
            if entry is not None:
                direction, event = entry
                if active is not None:
                    raise RuntimeError(
                        f"directional replay invariant violated: new {direction} entry while "
                        f"{active['direction']} trade is active at {bar.ts.isoformat()}"
                    )
                active = {
                    "direction": direction,
                    "entry_dt": event.event_time,
                    "entry_event": event.event_type,
                    "entry_price": float(event.price if event.price is not None else event.entry_price),
                }

            if active is not None:
                exit_event = _accepted_exit(decision, active["direction"])
                if exit_event is not None:
                    trades.append(_pair_trade(active=active, exit_event=exit_event))
                    active = None

        interesting = [r for r in rows if _interesting(r)]

        # A complete target session must not leave a coordinator-owned trade after 14:55.
        if coordinator.trade_owner != "NONE":
            raise RuntimeError(
                f"directional replay invariant violated: owner still active after session {current}: "
                f"{coordinator.trade_owner}"
            )

        _write_csv(session_dir/"directional-candle-by-candle.csv", rows)
        _write_csv(session_dir/"directional-events.csv", interesting)
        _write_csv(session_dir/"directional-trades.csv", [asdict(x) for x in trades])
        (session_dir/"directional-candle-by-candle.json").write_text(
            json.dumps(rows, indent=2, default=str) + "\n", encoding="utf-8"
        )
        (session_dir/"directional-events.json").write_text(
            json.dumps(interesting, indent=2, default=str) + "\n", encoding="utf-8"
        )
        _write_manual_validation(
            session_dir/"directional-manual-validation.txt",
            session_date=current,
            rows=interesting,
            trades=trades,
        )

        suppressed_bull = sum(
            any(x in BULLISH_ENTRY_EVENTS for x in (r["suppressed_events"] or "").split(",") if x)
            for r in rows
        )
        suppressed_bear = sum(
            any(x in BEARISH_ENTRY_EVENTS for x in (r["suppressed_events"] or "").split(",") if x)
            for r in rows
        )
        bull_arm_while_bear = sum(
            r["owner_after"] == "BEARISH" and bool(r["bullish_armed"]) for r in rows
        )
        bear_arm_while_bull = sum(
            r["owner_after"] == "BULLISH" and bool(r["bearish_armed"]) for r in rows
        )
        reversal_blocks = sum(
            bool(r["note"]) and "SAME_CANDLE" in str(r["note"]) for r in rows
        )

        bullish_points = sum(t.points for t in trades if t.direction == "BULLISH")
        bearish_points = sum(t.points for t in trades if t.direction == "BEARISH")
        summary = DirectionalSessionSummary(
            session_date=current.isoformat(),
            status="PASS",
            bars_5m=len(bars),
            directional_trades=len(trades),
            bullish_trades=sum(t.direction == "BULLISH" for t in trades),
            bearish_trades=sum(t.direction == "BEARISH" for t in trades),
            positive=sum(t.outcome == "POSITIVE" for t in trades),
            negative=sum(t.outcome == "NEGATIVE" for t in trades),
            flat=sum(t.outcome == "FLAT" for t in trades),
            net_directional_points=bullish_points + bearish_points,
            bullish_points=bullish_points,
            bearish_points=bearish_points,
            suppressed_bullish_entries=suppressed_bull,
            suppressed_bearish_entries=suppressed_bear,
            bullish_armed_while_bearish_active=bull_arm_while_bear,
            bearish_armed_while_bullish_active=bear_arm_while_bull,
            same_candle_reversal_blocks=reversal_blocks,
        )
        session_summaries.append(summary)
        all_trades.extend(trades)
        all_interesting.extend(interesting)
        all_candles.extend(rows)

        current += timedelta(days=1)

    missing = [s.session_date for s in session_summaries if s.status != "PASS"]
    payload = {
        "model": MODEL,
        "status": "PASS" if not missing else "PARTIAL",
        "underlying": underlying,
        "target_dates": [d.isoformat() for d in targets],
        "warmup_calendar_days": warmup_calendar_days,
        "observation_only": True,
        "execution_enabled": False,
        "paper_order_enabled": False,
        "option_selection_enabled": False,
        "whipsaw_mitigation_status": "DEFERRED",
        "directional_rules": {
            "active_owner_exclusive": True,
            "opposite_armed_informational": True,
            "opposite_entry_blocked_while_active": True,
            "same_candle_reversal": False,
            "post_exit_armed_can_continue_next_completed_candle": True,
        },
        "summary": {
            "sessions_requested": len(targets),
            "sessions_passed": sum(s.status == "PASS" for s in session_summaries),
            "sessions_unavailable": sum(s.status != "PASS" for s in session_summaries),
            "directional_trades": len(all_trades),
            "bullish_trades": sum(t.direction == "BULLISH" for t in all_trades),
            "bearish_trades": sum(t.direction == "BEARISH" for t in all_trades),
            "positive": sum(t.outcome == "POSITIVE" for t in all_trades),
            "negative": sum(t.outcome == "NEGATIVE" for t in all_trades),
            "flat": sum(t.outcome == "FLAT" for t in all_trades),
            "net_directional_points": sum(t.points for t in all_trades),
            "bullish_points": sum(t.points for t in all_trades if t.direction == "BULLISH"),
            "bearish_points": sum(t.points for t in all_trades if t.direction == "BEARISH"),
            "suppressed_bullish_entries": sum(s.suppressed_bullish_entries for s in session_summaries),
            "suppressed_bearish_entries": sum(s.suppressed_bearish_entries for s in session_summaries),
            "bullish_armed_while_bearish_active": sum(s.bullish_armed_while_bearish_active for s in session_summaries),
            "bearish_armed_while_bullish_active": sum(s.bearish_armed_while_bullish_active for s in session_summaries),
            "same_candle_reversal_blocks": sum(s.same_candle_reversal_blocks for s in session_summaries),
        },
        "sessions": [asdict(x) for x in session_summaries],
        "trades": [asdict(x) for x in all_trades],
        "data_availability": data_availability,
        "manual_validation_required": True,
    }

    (out_root/"multi-session-directional-summary.json").write_text(
        json.dumps(payload, indent=2, default=str) + "\n", encoding="utf-8"
    )
    _write_csv(out_root/"multi-session-directional-sessions.csv", [asdict(x) for x in session_summaries])
    _write_csv(out_root/"multi-session-directional-trades.csv", [asdict(x) for x in all_trades])
    _write_csv(out_root/"multi-session-directional-events.csv", all_interesting)
    _write_csv(out_root/"multi-session-directional-candle-by-candle.csv", all_candles)
    return payload
