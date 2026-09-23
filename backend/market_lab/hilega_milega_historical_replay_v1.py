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
                "bar_open": p.get("bar_open"),
                "bar_high": p.get("bar_high"),
                "bar_low": p.get("bar_low"),
                "bar_close": p.get("bar_close"),
                "bar_volume": p.get("bar_volume"),
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



def _yn(value: Any) -> str:
    if value is None:
        return "NA"
    return "YES" if bool(value) else "NO"


def _fmt_num(value: Any, digits: int = 2) -> str:
    if value is None:
        return "NA"
    try:
        return f"{float(value):.{digits}f}"
    except (TypeError, ValueError):
        return str(value)


def _human_interpretation(row: dict[str, Any]) -> str:
    d = row.get("final_decision")
    if d == "ENTRY_ROUTE_A":
        return "Fresh RSI upward cross of EMA3 confirmed immediately: RSI was above 50 and above WMA21."
    if d == "ENTRY_ROUTE_B":
        return "Path1 was armed and Route B confirmed because RSI or EMA3 was above WMA21 while both RSI and EMA3 were rising."
    if d == "ENTRY_OPENING":
        return "Opening path completed: 09:15 full alignment survived the 09:20 and 09:25 RSI-above-WMA21 holds."
    if d == "STRUCTURAL_EXIT":
        return "Active bullish structure ended on the first closed candle where RSI crossed below WMA21."
    if d == "SESSION_CUTOFF_EXIT":
        return "Active shadow position was closed at the 14:55 candle open because the hard session cutoff was reached."
    if d == "ARM_CANCELLED_1455":
        return "Armed Path1 setup was cancelled at 14:55; no new entries are allowed after the cutoff."
    if d == "ARMED_WAITING":
        return "Fresh RSI-upward-EMA3 cross armed Path1, but immediate entry conditions were incomplete; Route B remains eligible on later candles."
    if d == "WAIT_ROUTE_B":
        return "Path1 remains armed. Route B has not yet satisfied every structural/rising condition."
    if d == "OPENING_PROGRESS":
        return "Opening setup is still progressing through its required 09:15/09:20/09:25 confirmation sequence."
    if d == "OPENING_REJECTED":
        return "Opening setup was rejected at the current checkpoint; later Path1 signals remain allowed."
    if row.get("state_before") == "BULLISH_ACTIVE":
        return "Bullish position remains active; no structural exit condition was triggered on this candle."
    return "No strategy transition occurred on this candle."


def _all_decision_rows(audit_rows: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
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
        event_types = [str(r.get("status")) for r in transitions]
        state_before = p.get("state_before")

        final_decision = "NO_ACTION"
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
        elif "SESSION_CUTOFF_ARM_CANCELLED" in event_types:
            final_decision = "ARM_CANCELLED_1455"
        elif "PATH1_ARMED_RSI_CROSS_EMA3_UP" in event_types:
            final_decision = "ARMED_WAITING"
        elif any(e.startswith("OPENING_REJECTED") for e in event_types):
            final_decision = "OPENING_REJECTED"
        elif any(e.startswith("OPENING_") for e in event_types):
            final_decision = "OPENING_PROGRESS"
        elif state_before == "PATH1_ARMED":
            final_decision = "WAIT_ROUTE_B"
        elif state_before == "BULLISH_ACTIVE":
            final_decision = "HOLD_ACTIVE"

        route_a_fail = rp.get("route_a_fail_reasons") or []
        route_b_fail = rp.get("route_b_fail_reasons") or []
        reasons: list[str] = []
        if final_decision == "ENTRY_ROUTE_A":
            reasons = ["FRESH_RSI_CROSS_EMA3_UP", "RSI_ABOVE_50", "RSI_ABOVE_WMA21"]
        elif final_decision == "ENTRY_ROUTE_B":
            reasons = ["PATH1_ARMED_OR_FRESH_CROSS", "RSI_OR_EMA_ABOVE_WMA21", "RSI_RISING", "EMA_RISING"]
        elif final_decision == "STRUCTURAL_EXIT":
            reasons = ["PREVIOUS_RSI_GTE_PREVIOUS_WMA21", "CURRENT_RSI_LT_WMA21"]
        elif final_decision in {"SESSION_CUTOFF_EXIT", "ARM_CANCELLED_1455"}:
            reasons = ["HARD_SESSION_CUTOFF_14_55"]
        elif final_decision in {"ARMED_WAITING", "WAIT_ROUTE_B"}:
            reasons = list(dict.fromkeys(route_a_fail + route_b_fail))
        elif final_decision.startswith("OPENING"):
            if p.get("full_alignment"):
                reasons.append("FULL_ALIGNMENT")
            if p.get("rsi_gt_wma"):
                reasons.append("RSI_ABOVE_WMA21")

        row = {
            "checkpoint": checkpoint,
            "time": checkpoint[11:16],
            "bar_open": p.get("bar_open"),
            "bar_high": p.get("bar_high"),
            "bar_low": p.get("bar_low"),
            "bar_close": p.get("bar_close"),
            "bar_volume": p.get("bar_volume"),
            "state_before": state_before,
            "state_after": rp.get("state_after"),
            "final_decision": final_decision,
            "reasons": ",".join(reasons),
            "events": ",".join(event_types),
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
            "route_a_fail_reasons": ",".join(route_a_fail),
            "route_b_eligible": rp.get("route_b_eligible"),
            "route_b_pass": rp.get("route_b_pass"),
            "route_b_fail_reasons": ",".join(route_b_fail),
        }
        row["interpretation"] = _human_interpretation(row)
        out.append(row)
    return out


def _annotate_decisions_with_trade_outcome(
    rows: Sequence[dict[str, Any]], trades: Sequence[TradeRow]
) -> list[dict[str, Any]]:
    by_entry = {(t.session_date, t.entry_time): t for t in trades}
    out: list[dict[str, Any]] = []
    for source in rows:
        row = dict(source)
        key = (row.get("session_date"), row.get("time"))
        trade = by_entry.get(key)
        if trade and str(row.get("final_decision", "")).startswith("ENTRY_"):
            row.update({
                "retrospective_outcome": trade.outcome,
                "retrospective_exit_time": trade.exit_time,
                "retrospective_exit_reason": trade.exit_reason,
                "retrospective_points": trade.points,
            })
        else:
            row.update({
                "retrospective_outcome": "",
                "retrospective_exit_time": "",
                "retrospective_exit_reason": "",
                "retrospective_points": "",
            })
        out.append(row)
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
    lines = [
        f"HILEGA-MILEGA DECISION AUDIT — SIGNAL DETAIL — {session_date.isoformat()}",
        "=" * 100,
        "Causal strategy evidence is shown separately from retrospective trade outcome.",
        "",
    ]
    for r in rows:
        lines.extend([
            "=" * 100,
            f"{r['time']}  {r['final_decision']}",
            "=" * 100,
            "",
            "TIME / PRICE",
            f"  Checkpoint        : {r['checkpoint']}",
            f"  Open              : {_fmt_num(r.get('bar_open'))}",
            f"  High              : {_fmt_num(r.get('bar_high'))}",
            f"  Low               : {_fmt_num(r.get('bar_low'))}",
            f"  Close             : {_fmt_num(r.get('bar_close'))}",
            "",
            "INDICATORS",
            f"  RSI9              : {_fmt_num(r.get('rsi9'))}",
            f"  EMA3(RSI)         : {_fmt_num(r.get('ema3_rsi'))}",
            f"  WMA21(RSI)        : {_fmt_num(r.get('wma21_rsi'))}",
            f"  Previous RSI9     : {_fmt_num(r.get('previous_rsi9'))}",
            f"  Previous EMA3     : {_fmt_num(r.get('previous_ema3_rsi'))}",
            f"  Previous WMA21    : {_fmt_num(r.get('previous_wma21_rsi'))}",
            "",
            "STRUCTURAL CHECKS",
            f"  RSI crosses EMA up: {_yn(r.get('rsi_cross_ema_up'))}",
            f"  RSI crosses WMA dn: {_yn(r.get('rsi_cross_wma_down'))}",
            f"  RSI > 50          : {_yn(r.get('rsi_gt_50'))}",
            f"  RSI > WMA21       : {_yn(r.get('rsi_gt_wma'))}",
            f"  EMA3 > WMA21      : {_yn(r.get('ema_gt_wma'))}",
            f"  RSI rising        : {_yn(r.get('rsi_rising'))}",
            f"  EMA3 rising       : {_yn(r.get('ema_rising'))}",
            f"  FULL alignment    : {_yn(r.get('full_alignment'))}",
            "",
            "ROUTE A",
            f"  Eligible          : {_yn(r.get('route_a_eligible'))}",
            f"  Passed            : {_yn(r.get('route_a_pass'))}",
            f"  Failure reason(s) : {r.get('route_a_fail_reasons') or '-'}",
            "",
            "ROUTE B",
            f"  Eligible          : {_yn(r.get('route_b_eligible'))}",
            f"  Passed            : {_yn(r.get('route_b_pass'))}",
            f"  Failure reason(s) : {r.get('route_b_fail_reasons') or '-'}",
            "",
            "STRATEGY DECISION",
            f"  State before      : {r.get('state_before')}",
            f"  State after       : {r.get('state_after')}",
            f"  Decision          : {r.get('final_decision')}",
            f"  Why               : {r.get('reasons') or '-'}",
            f"  Events            : {r.get('events') or '-'}",
            "",
            "INTERPRETATION",
            f"  {_human_interpretation(r)}",
        ])
        if r.get("retrospective_outcome"):
            lines.extend([
                "",
                "RETROSPECTIVE OUTCOME — NOT AN INPUT TO THE DECISION",
                f"  Outcome           : {r.get('retrospective_outcome')}",
                f"  Exit time         : {r.get('retrospective_exit_time')}",
                f"  Exit reason       : {r.get('retrospective_exit_reason')}",
                f"  Chart points      : {_fmt_num(r.get('retrospective_points'))}",
            ])
        lines.append("")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _write_candle_by_candle_text(path: Path, session_date: date, rows: Sequence[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        f"HILEGA-MILEGA CANDLE-BY-CANDLE STRATEGY AUDIT — {session_date.isoformat()}",
        "=" * 132,
        "Every completed 5-minute candle is a causal snapshot. Retrospective outcome is excluded from this report.",
        "",
        "TIME   CLOSE      RSI9    EMA3   WMA21  XUP XDN >50 >WMA E>W RUP EUP  STATE BEFORE -> AFTER             DECISION",
        "-" * 132,
    ]
    for r in rows:
        lines.append(
            f"{r['time']:5} "
            f"{_fmt_num(r.get('bar_close')):>9} "
            f"{_fmt_num(r.get('rsi9')):>7} "
            f"{_fmt_num(r.get('ema3_rsi')):>7} "
            f"{_fmt_num(r.get('wma21_rsi')):>7}  "
            f"{_yn(r.get('rsi_cross_ema_up'))[:1]:>3} "
            f"{_yn(r.get('rsi_cross_wma_down'))[:1]:>3} "
            f"{_yn(r.get('rsi_gt_50'))[:1]:>3} "
            f"{_yn(r.get('rsi_gt_wma'))[:1]:>4} "
            f"{_yn(r.get('ema_gt_wma'))[:1]:>3} "
            f"{_yn(r.get('rsi_rising'))[:1]:>3} "
            f"{_yn(r.get('ema_rising'))[:1]:>3}  "
            f"{str(r.get('state_before')):12} -> {str(r.get('state_after')):12}  "
            f"{r.get('final_decision')}"
        )
        if r.get("reasons"):
            lines.append(f"      WHY: {r['reasons']}")
        if r.get("events"):
            lines.append(f"      EVENTS: {r['events']}")
        if r.get("final_decision") not in {"NO_ACTION", "HOLD_ACTIVE"}:
            lines.append(f"      INTERPRETATION: {r.get('interpretation')}")
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
    all_candle_decisions: list[dict[str, Any]] = []
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
        all_candle_decisions = _all_decision_rows(audit_rows)
        for row in decisions:
            row["session_date"] = current.isoformat()
        for row in all_candle_decisions:
            row["session_date"] = current.isoformat()
        trades = _pair_trades(events, current)

        trade_dicts = [asdict(t) for t in trades]
        decision_dicts = _annotate_decisions_with_trade_outcome(decisions, trades)
        all_candle_dicts = list(all_candle_decisions)
        _write_csv(session_dir / "trades.csv", trade_dicts)
        _write_csv(session_dir / "signal-decision-audit.csv", decision_dicts)
        (session_dir / "signal-decision-audit.json").write_text(
            json.dumps(decision_dicts, indent=2, default=str) + "\n",
            encoding="utf-8",
        )
        _write_decision_text(session_dir / "signal-decision-audit.txt", current, decision_dicts)
        _write_csv(session_dir / "candle-by-candle-strategy-audit.csv", all_candle_dicts)
        (session_dir / "candle-by-candle-strategy-audit.json").write_text(
            json.dumps(all_candle_dicts, indent=2, default=str) + "\n",
            encoding="utf-8",
        )
        _write_candle_by_candle_text(
            session_dir / "candle-by-candle-strategy-audit.txt", current, all_candle_dicts
        )

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
        all_decisions.extend(decision_dicts)
        all_candle_decisions.extend(all_candle_dicts)
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
    _write_csv(
        out_root / "multi-session-candle-by-candle-strategy-audit.csv",
        all_candle_decisions,
    )

    return payload
