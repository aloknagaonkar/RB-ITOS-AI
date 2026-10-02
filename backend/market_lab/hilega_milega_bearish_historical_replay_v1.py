from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Sequence

from .hilega_milega_bearish_strategy_v1 import (
    HilegaMilegaBearishEngineV1,
    STRATEGY_ID,
    STRATEGY_VERSION,
)
from .hilega_milega_historical_replay_v1 import (
    HistoricalUnderlyingGateway,
    UNDERLYING,
    aggregate_exact_5m,
    load_or_fetch_1m,
    _write_csv,
)
from .live_shadow_step_audit_v1 import ShadowStepAuditStoreV1

MODEL = "HILEGA_MILEGA_BEARISH_HISTORICAL_REPLAY_V1"
ENTRY_EVENTS = {
    "ENTRY_OPENING_BEARISH_CONFIRMED",
    "ENTRY_BEARISH_ROUTE_A_CROSS_RSI50_BELOW_WMA21",
    "ENTRY_BEARISH_ROUTE_B_STRUCTURAL",
}
EXIT_EVENTS = {
    "STRUCTURAL_EXIT_BEARISH_RSI_CROSS_ABOVE_WMA21",
    "BEARISH_SESSION_CUTOFF_EXIT_1455_OPEN",
}


@dataclass(frozen=True)
class BearishTradeRow:
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
class BearishSessionSummary:
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


def _audit_index(rows: Sequence[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    out: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        cp = row.get("checkpoint")
        if cp:
            out.setdefault(cp, []).append(row)
    return out


def _decision_rows(audit_rows: Sequence[dict[str, Any]], *, include_all: bool) -> list[dict[str, Any]]:
    grouped = _audit_index(audit_rows)
    out: list[dict[str, Any]] = []
    for checkpoint, rows in sorted(grouped.items()):
        decision = next(
            (r for r in rows if r.get("stage") == "STRATEGY_DECISION" and r.get("status") == "EVALUATED"),
            None,
        )
        result = next((r for r in rows if r.get("stage") == "STRATEGY_DECISION_RESULT"), None)
        if decision is None:
            continue
        p = decision.get("payload") or {}
        rp = (result or {}).get("payload") or {}
        transitions = [r for r in rows if r.get("stage") == "STRATEGY_TRANSITION"]
        events = [str(r.get("status")) for r in transitions]
        state_before = p.get("state_before")

        final = "NO_ACTION"
        if "ENTRY_BEARISH_ROUTE_A_CROSS_RSI50_BELOW_WMA21" in events:
            final = "ENTRY_ROUTE_A"
        elif "ENTRY_BEARISH_ROUTE_B_STRUCTURAL" in events:
            final = "ENTRY_ROUTE_B"
        elif "ENTRY_OPENING_BEARISH_CONFIRMED" in events:
            final = "ENTRY_OPENING"
        elif "STRUCTURAL_EXIT_BEARISH_RSI_CROSS_ABOVE_WMA21" in events:
            final = "STRUCTURAL_EXIT"
        elif "BEARISH_SESSION_CUTOFF_EXIT_1455_OPEN" in events:
            final = "SESSION_CUTOFF_EXIT"
        elif "BEARISH_SESSION_CUTOFF_ARM_CANCELLED" in events:
            final = "ARM_CANCELLED_1455"
        elif "BEARISH_PATH1_ARMED_RSI_CROSS_EMA3_DOWN" in events:
            final = "ARMED_WAITING"
        elif any(e.startswith("OPENING_BEARISH_REJECTED") for e in events):
            final = "OPENING_REJECTED"
        elif any(e.startswith("OPENING_BEARISH_") for e in events):
            final = "OPENING_PROGRESS"
        elif state_before == "BEARISH_PATH1_ARMED":
            final = "WAIT_ROUTE_B"
        elif state_before == "BEARISH_ACTIVE" or rp.get("state_after") == "BEARISH_ACTIVE":
            final = "HOLD_ACTIVE"

        interesting = (
            final != "NO_ACTION"
            or bool(p.get("rsi_cross_ema_down"))
            or bool(p.get("rsi_cross_wma_up"))
            or checkpoint[11:16] in {"09:15", "09:20", "09:25", "14:55"}
        )
        if not include_all and not interesting:
            continue

        reasons: list[str] = []
        if final == "ENTRY_ROUTE_A":
            reasons = ["FRESH_RSI_CROSS_EMA3_DOWN", "RSI_BELOW_50", "RSI_BELOW_WMA21"]
        elif final == "ENTRY_ROUTE_B":
            reasons = ["BEARISH_PATH1_ARMED_OR_FRESH_CROSS", "RSI_OR_EMA_BELOW_WMA21", "RSI_FALLING", "EMA_FALLING"]
        elif final == "STRUCTURAL_EXIT":
            reasons = ["PREVIOUS_RSI_LTE_PREVIOUS_WMA21", "CURRENT_RSI_GT_WMA21"]
        elif final in {"SESSION_CUTOFF_EXIT", "ARM_CANCELLED_1455"}:
            reasons = ["HARD_SESSION_CUTOFF_14_55"]
        elif final in {"ARMED_WAITING", "WAIT_ROUTE_B"}:
            reasons.extend(rp.get("route_a_fail_reasons") or [])
            reasons.extend(rp.get("route_b_fail_reasons") or [])
        elif final.startswith("OPENING"):
            if p.get("full_alignment"):
                reasons.append("FULL_BEARISH_ALIGNMENT")
            if p.get("rsi_lt_wma"):
                reasons.append("RSI_BELOW_WMA21")

        out.append(
            {
                "checkpoint": checkpoint,
                "time": checkpoint[11:16],
                "direction": "BEARISH",
                "state_before": state_before,
                "state_after": rp.get("state_after"),
                "final_decision": final,
                "reasons": ",".join(dict.fromkeys(reasons)),
                "events": ",".join(events),
                "bar_open": p.get("bar_open"),
                "bar_high": p.get("bar_high"),
                "bar_low": p.get("bar_low"),
                "bar_close": p.get("bar_close"),
                "bar_volume": p.get("bar_volume"),
                "rsi9": p.get("rsi9"),
                "ema3_rsi": p.get("ema3_rsi"),
                "wma21_rsi": p.get("wma21_rsi"),
                "previous_rsi9": p.get("previous_rsi9"),
                "previous_ema3_rsi": p.get("previous_ema3_rsi"),
                "previous_wma21_rsi": p.get("previous_wma21_rsi"),
                "rsi_cross_ema_down": p.get("rsi_cross_ema_down"),
                "rsi_cross_wma_up": p.get("rsi_cross_wma_up"),
                "rsi_lt_50": p.get("rsi_lt_50"),
                "rsi_lt_wma": p.get("rsi_lt_wma"),
                "ema_lt_wma": p.get("ema_lt_wma"),
                "rsi_falling": p.get("rsi_falling"),
                "ema_falling": p.get("ema_falling"),
                "full_alignment": p.get("full_alignment"),
                "route_a_eligible": rp.get("route_a_eligible"),
                "route_a_pass": rp.get("route_a_pass"),
                "route_a_fail_reasons": ",".join(rp.get("route_a_fail_reasons") or []),
                "route_b_eligible": rp.get("route_b_eligible"),
                "route_b_pass": rp.get("route_b_pass"),
                "route_b_fail_reasons": ",".join(rp.get("route_b_fail_reasons") or []),
                "selected_route": rp.get("selected_route"),
            }
        )
    return out


def _pair_trades(events: Sequence[Any], session_date: date) -> list[BearishTradeRow]:
    active: dict[str, Any] | None = None
    trades: list[BearishTradeRow] = []
    for e in events:
        if e.event_type in ENTRY_EVENTS:
            active = {
                "entry_time": e.event_time,
                "source": e.source or "UNKNOWN",
                "entry_price": float(e.price if e.price is not None else e.entry_price),
            }
            continue
        if e.event_type not in EXIT_EVENTS or active is None:
            continue
        exit_price = float(e.price)
        points = float(e.points if e.points is not None else active["entry_price"] - exit_price)
        outcome = "POSITIVE" if points > 0 else ("NEGATIVE" if points < 0 else "FLAT")
        trades.append(
            BearishTradeRow(
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


def _write_validation_text(path: Path, session_date: date, rows: Sequence[dict[str, Any]]) -> None:
    lines = [
        f"HILEGA-MILEGA BEARISH MANUAL VALIDATION — {session_date.isoformat()}",
        "=" * 118,
        "Candidate mirror rules only. Review candle-by-candle before freezing bearish production rules.",
        "",
        "TIME   CLOSE      RSI9    EMA3   WMA21  XDN XUP <50 <WMA E<W RDN EDN  STATE BEFORE -> AFTER                 DECISION",
        "-" * 118,
    ]
    def yn(v: Any) -> str:
        return "Y" if v is True else ("N" if v is False else "-")
    def n(v: Any) -> str:
        return "NA" if v is None else f"{float(v):.2f}"
    for r in rows:
        lines.append(
            f"{r['time']:5} {n(r.get('bar_close')):>9} {n(r.get('rsi9')):>7} {n(r.get('ema3_rsi')):>7} "
            f"{n(r.get('wma21_rsi')):>7}  {yn(r.get('rsi_cross_ema_down')):>3} {yn(r.get('rsi_cross_wma_up')):>3} "
            f"{yn(r.get('rsi_lt_50')):>3} {yn(r.get('rsi_lt_wma')):>4} {yn(r.get('ema_lt_wma')):>3} "
            f"{yn(r.get('rsi_falling')):>3} {yn(r.get('ema_falling')):>3}  "
            f"{str(r.get('state_before')):20} -> {str(r.get('state_after')):20} {r.get('final_decision')}"
        )
        if r.get("reasons"):
            lines.append(f"      WHY: {r['reasons']}")
        if r.get("events"):
            lines.append(f"      EVENTS: {r['events']}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def replay_bearish_sessions(
    *,
    gateway: HistoricalUnderlyingGateway,
    dates: Sequence[date],
    underlying: str = UNDERLYING,
    warmup_calendar_days: int = 45,
    cache_root: str | Path = "data/historical-evidence/hilega-milega-underlying-cache-v1",
    output_root: str | Path = "data/historical-evidence/hilega-milega-bearish-replay-v1",
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

    engine = HilegaMilegaBearishEngineV1(audit_store=None)
    session_summaries: list[BearishSessionSummary] = []
    all_trades: list[BearishTradeRow] = []
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
                    BearishSessionSummary(
                        current.isoformat(), "UNAVAILABLE", 0, 0, 0, 0, 0, 0.0,
                        0, 0, 0, 0, 0, 0, "No historical underlying candles returned."
                    )
                )
            current += timedelta(days=1)
            continue

        bars = aggregate_exact_5m(candles, current)
        if current not in target_set:
            engine.previous_indicators = None
            engine.previous_bar = None
            for bar in bars:
                engine.indicators.update(bar.close)
            current += timedelta(days=1)
            continue

        session_dir = out_root/current.isoformat()
        session_dir.mkdir(parents=True, exist_ok=True)
        audit_path = session_dir/"step-audit.jsonl"
        if audit_path.exists():
            audit_path.unlink()
        store = ShadowStepAuditStoreV1(audit_path)
        engine.audit_store = store

        events: list[Any] = []
        for bar in bars:
            events.extend(engine.on_bar(bar))

        ok, issue = store.verify_chain()
        if not ok:
            raise RuntimeError(f"bearish step audit chain invalid for {current}: {issue}")

        audit_rows = store.read_all()
        interesting = _decision_rows(audit_rows, include_all=False)
        candles_all = _decision_rows(audit_rows, include_all=True)
        for row in interesting:
            row["session_date"] = current.isoformat()
        for row in candles_all:
            row["session_date"] = current.isoformat()

        trades = _pair_trades(events, current)
        trade_dicts = [asdict(x) for x in trades]
        _write_csv(session_dir/"bearish-trades.csv", trade_dicts)
        _write_csv(session_dir/"bearish-signal-decision-audit.csv", interesting)
        _write_csv(session_dir/"bearish-candle-by-candle-audit.csv", candles_all)
        (session_dir/"bearish-signal-decision-audit.json").write_text(
            json.dumps(interesting, indent=2, default=str) + "\n", encoding="utf-8"
        )
        (session_dir/"bearish-candle-by-candle-audit.json").write_text(
            json.dumps(candles_all, indent=2, default=str) + "\n", encoding="utf-8"
        )
        _write_validation_text(session_dir/"bearish-manual-validation.txt", current, interesting)

        pos = sum(t.outcome == "POSITIVE" for t in trades)
        neg = sum(t.outcome == "NEGATIVE" for t in trades)
        flat = sum(t.outcome == "FLAT" for t in trades)
        summary = BearishSessionSummary(
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
            opening_trades=sum(t.source == "BEARISH_OPENING_PATH" for t in trades),
            structural_exits=sum(t.exit_reason == "RSI_CROSS_ABOVE_WMA21" for t in trades),
            cutoff_exits=sum(t.exit_reason == "SESSION_CUTOFF_14_55_OPEN" for t in trades),
            armed_events=sum(e.event_type == "BEARISH_PATH1_ARMED_RSI_CROSS_EMA3_DOWN" for e in events),
        )
        session_summaries.append(summary)
        all_trades.extend(trades)
        all_interesting.extend(interesting)
        all_candles.extend(candles_all)
        current += timedelta(days=1)

    missing = [s.session_date for s in session_summaries if s.status != "PASS"]
    payload = {
        "model": MODEL,
        "strategy_id": STRATEGY_ID,
        "strategy_version": STRATEGY_VERSION,
        "status": "PASS" if not missing else "PARTIAL",
        "underlying": underlying,
        "target_dates": [d.isoformat() for d in targets],
        "warmup_calendar_days": warmup_calendar_days,
        "execution_enabled": False,
        "paper_order_enabled": False,
        "observation_only": True,
        "rule_status": "CANDIDATE_MIRROR_UNDER_VALIDATION",
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
            "opening_trades": sum(t.source == "BEARISH_OPENING_PATH" for t in all_trades),
            "structural_exits": sum(t.exit_reason == "RSI_CROSS_ABOVE_WMA21" for t in all_trades),
            "cutoff_exits": sum(t.exit_reason == "SESSION_CUTOFF_14_55_OPEN" for t in all_trades),
        },
        "sessions": [asdict(x) for x in session_summaries],
        "trades": [asdict(x) for x in all_trades],
        "data_availability": data_availability,
        "manual_validation_required": True,
    }
    (out_root/"multi-session-bearish-summary.json").write_text(
        json.dumps(payload, indent=2, default=str) + "\n", encoding="utf-8"
    )
    _write_csv(out_root/"multi-session-bearish-sessions.csv", [asdict(x) for x in session_summaries])
    _write_csv(out_root/"multi-session-bearish-trades.csv", [asdict(x) for x in all_trades])
    _write_csv(out_root/"multi-session-bearish-signal-decision-audit.csv", all_interesting)
    _write_csv(out_root/"multi-session-bearish-candle-by-candle-audit.csv", all_candles)
    return payload
