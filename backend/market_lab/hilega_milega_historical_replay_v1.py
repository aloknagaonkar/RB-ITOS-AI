from __future__ import annotations

import csv
import json
from dataclasses import asdict, dataclass
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import Any, Iterable, Protocol, Sequence
from zoneinfo import ZoneInfo

from .domain import HistoricalCandle
from .hilega_milega_strategy_v1 import (
    FiveMinuteBar,
    HilegaMilegaBullishEngineV1,
    STRATEGY_ID,
    STRATEGY_VERSION,
)
from .live_shadow_step_audit_v1 import ShadowStepAuditStoreV1

IST = ZoneInfo("Asia/Kolkata")
UNDERLYING = "NSE_INDEX|Nifty 50"
MODEL = "HILEGA_MILEGA_HISTORICAL_MULTI_SESSION_REPLAY_V1"
CACHE_SCHEMA_VERSION = 1
ENTRY_EVENT_PREFIX = "ENTRY_"
EXIT_EVENTS = {
    "STRUCTURAL_EXIT_RSI_CROSS_BELOW_WMA21",
    "SESSION_CUTOFF_EXIT_1455_OPEN",
}


class HistoricalUnderlyingGateway(Protocol):
    def historical_candles(
        self, instrument_key: str, session_date: date
    ) -> list[HistoricalCandle]: ...


@dataclass(frozen=True)
class TradeRow:
    session_date: str
    entry_time: str
    source: str
    entry_price: float
    exit_time: str
    exit_reason: str
    exit_price: float
    points: float
    outcome: str


@dataclass(frozen=True)
class SessionSummary:
    session_date: str
    status: str
    bars_5m: int
    trades: int
    positive: int
    negative: int
    flat: int
    net_points: float
    route_a_trades: int
    route_b_trades: int
    opening_trades: int
    structural_exits: int
    cutoff_exits: int
    armed_events: int
    error: str | None = None


def _jsonable(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, tuple):
        return [_jsonable(x) for x in value]
    if isinstance(value, list):
        return [_jsonable(x) for x in value]
    if isinstance(value, dict):
        return {k: _jsonable(v) for k, v in value.items()}
    return value


def _cache_path(cache_root: str | Path, session_date: date) -> Path:
    return Path(cache_root) / f"{session_date.isoformat()}.json"


def _write_cache(path: Path, underlying: str, session_date: date, candles: Sequence[HistoricalCandle]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": CACHE_SCHEMA_VERSION,
        "underlying": underlying,
        "session_date": session_date.isoformat(),
        "candles": [
            {
                "timestamp": c.timestamp.isoformat(),
                "open": c.open,
                "high": c.high,
                "low": c.low,
                "close": c.close,
                "volume": c.volume,
                "open_interest": c.open_interest,
            }
            for c in candles
        ],
    }
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def _read_cache(path: Path, underlying: str, session_date: date) -> list[HistoricalCandle] | None:
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    if (
        payload.get("schema_version") != CACHE_SCHEMA_VERSION
        or payload.get("underlying") != underlying
        or payload.get("session_date") != session_date.isoformat()
        or not isinstance(payload.get("candles"), list)
    ):
        return None
    rows: list[HistoricalCandle] = []
    for x in payload["candles"]:
        ts = datetime.fromisoformat(x["timestamp"])
        rows.append(
            HistoricalCandle(
                provider="upstox",
                instrument_key=underlying,
                session_date=session_date,
                timestamp=ts,
                open=float(x["open"]),
                high=float(x["high"]),
                low=float(x["low"]),
                close=float(x["close"]),
                volume=None if x.get("volume") is None else int(x["volume"]),
                open_interest=None if x.get("open_interest") is None else int(x["open_interest"]),
            )
        )
    rows.sort(key=lambda c: c.timestamp)
    return rows


def load_or_fetch_1m(
    gateway: HistoricalUnderlyingGateway,
    *,
    underlying: str,
    session_date: date,
    cache_root: str | Path,
    refresh_cache: bool = False,
) -> list[HistoricalCandle]:
    path = _cache_path(cache_root, session_date)
    if not refresh_cache:
        cached = _read_cache(path, underlying, session_date)
        if cached is not None:
            return cached
    candles = sorted(
        gateway.historical_candles(underlying, session_date),
        key=lambda c: c.timestamp,
    )
    _write_cache(path, underlying, session_date, candles)
    return candles


def aggregate_exact_5m(
    candles: Iterable[HistoricalCandle], session_date: date
) -> list[FiveMinuteBar]:
    by_minute: dict[datetime, HistoricalCandle] = {}
    for c in candles:
        ts = c.timestamp.astimezone(IST).replace(second=0, microsecond=0)
        if ts.date() != session_date:
            continue
        if not (time(9, 15) <= ts.time() <= time(15, 29)):
            continue
        if ts in by_minute:
            raise ValueError(f"duplicate 1m candle at {ts.isoformat()}")
        by_minute[ts] = c

    bars: list[FiveMinuteBar] = []
    start = datetime.combine(session_date, time(9, 15), tzinfo=IST)
    for slot in range(75):
        label = start + timedelta(minutes=5 * slot)
        needed = [label + timedelta(minutes=i) for i in range(5)]
        present = [by_minute.get(ts) for ts in needed]
        if all(x is None for x in present):
            continue
        if any(x is None for x in present):
            missing = [ts.strftime("%H:%M") for ts, x in zip(needed, present) if x is None]
            raise ValueError(
                f"incomplete exact 5m candle {label.strftime('%H:%M')}; missing 1m: {','.join(missing)}"
            )
        xs = [x for x in present if x is not None]
        bars.append(
            FiveMinuteBar(
                ts=label,
                open=float(xs[0].open),
                high=max(float(x.high) for x in xs),
                low=min(float(x.low) for x in xs),
                close=float(xs[-1].close),
                volume=sum(int(x.volume or 0) for x in xs),
            )
        )
    return bars


def _audit_index(rows: Sequence[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    result: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        cp = row.get("checkpoint")
        if cp:
            result.setdefault(cp, []).append(row)
    return result


def _decision_reason_rows(audit_rows: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped = _audit_index(audit_rows)
    out: list[dict[str, Any]] = []
    for checkpoint, rows in sorted(grouped.items()):
        evaluated = next((r for r in rows if r.get("stage") == "STRATEGY_DECISION" and r.get("status") == "EVALUATED"), None)
        result = next((r for r in rows if r.get("stage") == "STRATEGY_DECISION_RESULT"), None)
        transitions = [r for r in rows if r.get("stage") == "STRATEGY_TRANSITION"]
        if evaluated is None:
            continue
        p = evaluated.get("payload", {})
        rp = result.get("payload", {}) if result else {}
        event_types = [r.get("status") for r in transitions]
        state_before = p.get("state_before")

        interesting = (
            bool(p.get("rsi_cross_ema_up"))
            or state_before == "PATH1_ARMED"
            or checkpoint[11:16] in {"09:15", "09:20", "09:25", "14:55"}
            or bool(p.get("rsi_cross_wma_down"))
            or bool(event_types)
        )
        if not interesting:
            continue

        final_decision = "NO_ENTRY"
        if "ENTRY_PATH1_ROUTE_A_CROSS_RSI50_ABOVE_WMA21" in event_types:
            final_decision = "ENTRY_ROUTE_A"
        elif "ENTRY_PATH1_ROUTE_B_STRUCTURAL" in event_types:
            final_decision = "ENTRY_ROUTE_B"
        elif "ENTRY_OPENING_BULLISH_CONFIRMED" in event_types:
            final_decision = "ENTRY_OPENING"
        elif "STRUCTURAL_EXIT_RSI_CROSS_BELOW_WMA21" in event_types:
            final_decision = "STRUCTURAL_EXIT"
        elif "SESSION_CUTOFF_EXIT_1455_OPEN" in event_types:
            final_decision = "SESSION_CUTOFF_EXIT"
        elif "PATH1_ARMED_RSI_CROSS_EMA3_UP" in event_types:
            final_decision = "ARMED_WAITING"
        elif "SESSION_CUTOFF_ARM_CANCELLED" in event_types:
            final_decision = "ARM_CANCELLED_1455"
        elif any(str(e).startswith("OPENING_REJECTED") for e in event_types):
            final_decision = "OPENING_REJECTED"
        elif any(str(e).startswith("OPENING_") for e in event_types):
            final_decision = "OPENING_PROGRESS"
        elif state_before == "PATH1_ARMED":
            final_decision = "WAIT_ROUTE_B"

        reasons: list[str] = []
        if final_decision in {"ARMED_WAITING", "NO_ENTRY"} and p.get("rsi_cross_ema_up"):
            reasons.extend(rp.get("route_a_fail_reasons") or [])
            reasons.extend(rp.get("route_b_fail_reasons") or [])
        elif final_decision == "WAIT_ROUTE_B":
            reasons.extend(rp.get("route_b_fail_reasons") or [])
        elif final_decision == "ENTRY_ROUTE_A":
            reasons.append("FRESH_RSI_CROSS_EMA3_UP")
            reasons.append("RSI_ABOVE_50")
            reasons.append("RSI_ABOVE_WMA21")
        elif final_decision == "ENTRY_ROUTE_B":
            reasons.append("PATH1_ARMED_OR_FRESH_CROSS")
            reasons.append("RSI_OR_EMA_ABOVE_WMA21")
            reasons.append("RSI_RISING")
            reasons.append("EMA_RISING")
        elif final_decision == "STRUCTURAL_EXIT":
            reasons.append("PREVIOUS_RSI_GTE_PREVIOUS_WMA21")
            reasons.append("CURRENT_RSI_LT_WMA21")
        elif final_decision == "SESSION_CUTOFF_EXIT":
            reasons.append("HARD_SESSION_CUTOFF_14_55")
        elif final_decision == "ARM_CANCELLED_1455":
            reasons.append("HARD_SESSION_CUTOFF_14_55")
        elif final_decision.startswith("OPENING"):
            if p.get("full_alignment"):
                reasons.append("FULL_ALIGNMENT")
            if p.get("rsi_gt_wma"):
                reasons.append("RSI_ABOVE_WMA21")

        out.append(
            {
                "checkpoint": checkpoint,
                "time": checkpoint[11:16],
                "state_before": state_before,
                "state_after": rp.get("state_after"),
                "final_decision": final_decision,
                "reasons": ",".join(dict.fromkeys(reasons)),
                "events": ",".join(str(x) for x in event_types),
                "rsi9": p.get("rsi9"),
                "ema3_rsi": p.get("ema3_rsi"),
                "wma21_rsi": p.get("wma21_rsi"),
                "previous_rsi9": p.get("previous_rsi9"),
                "previous_ema3_rsi": p.get("previous_ema3_rsi"),
                "previous_wma21_rsi": p.get("previous_wma21_rsi"),
                "rsi_cross_ema_up": p.get("rsi_cross_ema_up"),
                "rsi_cross_wma_down": p.get("rsi_cross_wma_down"),
                "rsi_gt_50": p.get("rsi_gt_50"),
                "rsi_gt_wma": p.get("rsi_gt_wma"),
                "ema_gt_wma": p.get("ema_gt_wma"),
                "rsi_rising": p.get("rsi_rising"),
                "ema_rising": p.get("ema_rising"),
                "full_alignment": p.get("full_alignment"),
                "route_a_eligible": rp.get("route_a_eligible"),
                "route_a_pass": rp.get("route_a_pass"),
                "route_a_fail_reasons": ",".join(rp.get("route_a_fail_reasons") or []),
                "route_b_eligible": rp.get("route_b_eligible"),
                "route_b_pass": rp.get("route_b_pass"),
                "route_b_fail_reasons": ",".join(rp.get("route_b_fail_reasons") or []),
            }
        )
    return out


def _pair_trades(events: Sequence[Any], session_date: date) -> list[TradeRow]:
    active: dict[str, Any] | None = None
    trades: list[TradeRow] = []
    for e in events:
        if e.event_type.startswith(ENTRY_EVENT_PREFIX):
            active = {
                "entry_time": e.event_time,
                "source": e.source or "UNKNOWN",
                "entry_price": float(e.price if e.price is not None else e.entry_price),
            }
            continue
        if e.event_type not in EXIT_EVENTS or active is None:
            continue
        exit_price = float(e.price)
        points = float(e.points if e.points is not None else exit_price - active["entry_price"])
        outcome = "POSITIVE" if points > 0 else ("NEGATIVE" if points < 0 else "FLAT")
        trades.append(
            TradeRow(
                session_date=session_date.isoformat(),
                entry_time=active["entry_time"].strftime("%H:%M"),
                source=active["source"],
                entry_price=active["entry_price"],
                exit_time=e.event_time.strftime("%H:%M"),
                exit_reason=e.exit_reason or e.event_type,
                exit_price=exit_price,
                points=points,
                outcome=outcome,
            )
        )
        active = None
    return trades


def _write_csv(path: Path, rows: Sequence[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def _write_decision_text(path: Path, session_date: date, rows: Sequence[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [f"HILEGA-MILEGA DECISION AUDIT — {session_date.isoformat()}", "=" * 88, ""]
    for r in rows:
        lines.extend(
            [
                f"{r['time']}  {r['final_decision']}  {r['state_before']} -> {r['state_after']}",
                f"  RSI9={r['rsi9']}  EMA3={r['ema3_rsi']}  WMA21={r['wma21_rsi']}",
                f"  Prev RSI={r['previous_rsi9']}  Prev EMA={r['previous_ema3_rsi']}  Prev WMA={r['previous_wma21_rsi']}",
                f"  Cross RSI↑EMA={r['rsi_cross_ema_up']}  Cross RSI↓WMA={r['rsi_cross_wma_down']}",
                f"  RSI>50={r['rsi_gt_50']}  RSI>WMA={r['rsi_gt_wma']}  EMA>WMA={r['ema_gt_wma']}",
                f"  RSI rising={r['rsi_rising']}  EMA rising={r['ema_rising']}  FULL={r['full_alignment']}",
                f"  Route A eligible/pass={r['route_a_eligible']}/{r['route_a_pass']}  fail={r['route_a_fail_reasons'] or '-'}",
                f"  Route B eligible/pass={r['route_b_eligible']}/{r['route_b_pass']}  fail={r['route_b_fail_reasons'] or '-'}",
                f"  WHY: {r['reasons'] or '-'}",
                f"  Events: {r['events'] or '-'}",
                "",
            ]
        )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def replay_sessions(
    *,
    gateway: HistoricalUnderlyingGateway,
    dates: Sequence[date],
    underlying: str = UNDERLYING,
    warmup_calendar_days: int = 45,
    cache_root: str | Path = "data/historical-evidence/hilega-milega-underlying-cache-v1",
    output_root: str | Path = "data/historical-evidence/hilega-milega-replay-v1",
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

    engine = HilegaMilegaBullishEngineV1(audit_store=None)
    session_summaries: list[SessionSummary] = []
    all_trades: list[TradeRow] = []
    all_decisions: list[dict[str, Any]] = []
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
                    SessionSummary(current.isoformat(), "UNAVAILABLE", 0, 0, 0, 0, 0, 0.0, 0, 0, 0, 0, 0, 0, "No historical underlying candles returned.")
                )
            current += timedelta(days=1)
            continue

        bars = aggregate_exact_5m(candles, current)
        if current not in target_set:
            # Preserve indicator continuity without creating strategy decisions.
            engine.previous_indicators = None
            engine.previous_bar = None
            for bar in bars:
                engine.indicators.update(bar.close)
            current += timedelta(days=1)
            continue

        session_dir = out_root / current.isoformat()
        session_dir.mkdir(parents=True, exist_ok=True)
        audit_path = session_dir / "step-audit.jsonl"
        if audit_path.exists():
            audit_path.unlink()
        store = ShadowStepAuditStoreV1(audit_path)
        engine.audit_store = store

        events = []
        for bar in bars:
            events.extend(engine.on_bar(bar))

        ok, error = store.verify_chain()
        if not ok:
            raise RuntimeError(f"step audit chain invalid for {current}: {error}")

        audit_rows = store.read_all()
        decisions = _decision_reason_rows(audit_rows)
        for row in decisions:
            row["session_date"] = current.isoformat()
        trades = _pair_trades(events, current)

        trade_dicts = [asdict(t) for t in trades]
        decision_dicts = list(decisions)
        _write_csv(session_dir / "trades.csv", trade_dicts)
        _write_csv(session_dir / "signal-decision-audit.csv", decision_dicts)
        (session_dir / "signal-decision-audit.json").write_text(
            json.dumps(decision_dicts, indent=2, default=str) + "\n",
            encoding="utf-8",
        )
        _write_decision_text(session_dir / "signal-decision-audit.txt", current, decision_dicts)

        pos = sum(t.outcome == "POSITIVE" for t in trades)
        neg = sum(t.outcome == "NEGATIVE" for t in trades)
        flat = sum(t.outcome == "FLAT" for t in trades)
        summary = SessionSummary(
            session_date=current.isoformat(),
            status="PASS",
            bars_5m=len(bars),
            trades=len(trades),
            positive=pos,
            negative=neg,
            flat=flat,
            net_points=sum(t.points for t in trades),
            route_a_trades=sum("ROUTE_A" in t.source for t in trades),
            route_b_trades=sum("ROUTE_B" in t.source for t in trades),
            opening_trades=sum(t.source == "OPENING_PATH" for t in trades),
            structural_exits=sum(t.exit_reason == "RSI_CROSS_BELOW_WMA21" for t in trades),
            cutoff_exits=sum(t.exit_reason == "SESSION_CUTOFF_14_55_OPEN" for t in trades),
            armed_events=sum(e.event_type == "PATH1_ARMED_RSI_CROSS_EMA3_UP" for e in events),
        )
        session_summaries.append(summary)
        all_trades.extend(trades)
        all_decisions.extend(decisions)
        current += timedelta(days=1)

    missing_targets = [s.session_date for s in session_summaries if s.status != "PASS"]
    payload = {
        "model": MODEL,
        "strategy_id": STRATEGY_ID,
        "strategy_version": STRATEGY_VERSION,
        "status": "PASS" if not missing_targets else "PARTIAL",
        "underlying": underlying,
        "target_dates": [d.isoformat() for d in targets],
        "warmup_calendar_days": warmup_calendar_days,
        "execution_enabled": False,
        "paper_order_enabled": False,
        "observation_only": True,
        "chart_validation_basis": {
            "entry": "SIGNAL_5M_CLOSE",
            "structural_exit": "EXIT_5M_CLOSE",
            "session_cutoff": "14:55_5M_OPEN",
            "option_pnl": False,
        },
        "summary": {
            "sessions_requested": len(targets),
            "sessions_passed": sum(s.status == "PASS" for s in session_summaries),
            "sessions_unavailable": sum(s.status != "PASS" for s in session_summaries),
            "trades": len(all_trades),
            "positive": sum(t.outcome == "POSITIVE" for t in all_trades),
            "negative": sum(t.outcome == "NEGATIVE" for t in all_trades),
            "flat": sum(t.outcome == "FLAT" for t in all_trades),
            "net_points": sum(t.points for t in all_trades),
            "route_a_trades": sum("ROUTE_A" in t.source for t in all_trades),
            "route_b_trades": sum("ROUTE_B" in t.source for t in all_trades),
            "opening_trades": sum(t.source == "OPENING_PATH" for t in all_trades),
            "structural_exits": sum(t.exit_reason == "RSI_CROSS_BELOW_WMA21" for t in all_trades),
            "cutoff_exits": sum(t.exit_reason == "SESSION_CUTOFF_14_55_OPEN" for t in all_trades),
        },
        "sessions": [asdict(x) for x in session_summaries],
        "trades": [asdict(x) for x in all_trades],
        "data_availability": data_availability,
    }

    (out_root / "multi-session-summary.json").write_text(
        json.dumps(payload, indent=2, default=str) + "\n", encoding="utf-8"
    )
    _write_csv(out_root / "multi-session-sessions.csv", [asdict(x) for x in session_summaries])
    _write_csv(out_root / "multi-session-trades.csv", [asdict(x) for x in all_trades])
    _write_csv(out_root / "multi-session-signal-decision-audit.csv", all_decisions)

    return payload
