from __future__ import annotations

import csv
import json
from dataclasses import asdict, dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Sequence

from .domain import IST
from .historical_option_ohlc_adapter_v1 import (
    OptionOHLCSesssion,
    choose_option_ohlc_session,
    instrument_candles,
)
from .hilega_milega_option_candidate_v1 import build_bullish_ce_candidate_set
from .hilega_milega_option_shadow_lifecycle_v1 import (
    HilegaMilegaOptionShadowLifecycleV1,
)

MODEL = "HILEGA_DIRECTIONAL_CE_ATM_PLUS_MINUS_2_HISTORICAL_SHADOW_V1"
SELECTION_POLICY = "ALL_ATM_PLUS_MINUS_2_CE_SHADOW"
ENTRY_SEMANTICS = "EXACT_1M_OPEN_AT_SIGNAL_BOUNDARY"
EXIT_SEMANTICS = "EXACT_1M_OPEN_AT_CAUSAL_EXIT_BOUNDARY"


@dataclass(frozen=True)
class CETradeShadowSummary:
    session_date: str
    trade_index: int
    entry_time: str
    exit_time: str
    entry_event: str
    exit_event: str
    signal_spot: float
    atm: float | None
    expiry: str | None
    status: str
    complete_legs: int
    issue: str | None


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
        writer = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def _dt(session_date: str, hhmm: str) -> datetime:
    h, m = map(int, hhmm.split(":"))
    y, mo, d = map(int, session_date.split("-"))
    return datetime(y, mo, d, h, m, tzinfo=IST)


def _contracts(session: OptionOHLCSesssion) -> list[dict[str, Any]]:
    """Adapt OHLC rows to the existing frozen CE candidate-builder contract."""
    seen: set[tuple[str, float, str]] = set()
    rows: list[dict[str, Any]] = []
    for row in session.rows:
        side = row.side.upper()
        ident = (row.instrument_key, float(row.strike), side)
        if ident in seen:
            continue
        seen.add(ident)
        rows.append(
            {
                "instrument_key": row.instrument_key,
                "strike_price": float(row.strike),
                # CE builder normalizes option_type/instrument_type, not `side`.
                "option_type": side,
                "expiry": row.expiry,
            }
        )
    return rows


def _option_source(session: OptionOHLCSesssion):
    def source(instrument_key: str):
        return instrument_candles(session, instrument_key=instrument_key, side="CE")
    return source


def _leg_rows(
    *,
    session_date: str,
    trade_index: int,
    snapshot: dict[str, Any],
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for leg in snapshot.get("legs", []):
        out.append(
            {
                "session_date": session_date,
                "trade_index": trade_index,
                "signal_bar": snapshot.get("signal_bar"),
                "signal_boundary": snapshot.get("signal_boundary"),
                "source": snapshot.get("source"),
                "signal_spot": snapshot.get("signal_spot"),
                "atm": snapshot.get("atm"),
                "expiry": snapshot.get("expiry"),
                "status": snapshot.get("status"),
                "strike": leg.get("strike"),
                "relation_to_atm": leg.get("relation_to_atm"),
                "side": leg.get("side"),
                "instrument_key": leg.get("instrument_key"),
                "entry_timestamp": leg.get("entry_timestamp"),
                "entry_open": leg.get("entry_open"),
                "latest_completed_minute": leg.get("latest_completed_minute"),
                "latest_close": leg.get("latest_close"),
                "current_points": leg.get("current_points"),
                "current_return_pct": leg.get("current_return_pct"),
                "mfe_points": leg.get("mfe_points"),
                "mfe_pct": leg.get("mfe_pct"),
                "mae_points": leg.get("mae_points"),
                "mae_pct": leg.get("mae_pct"),
                "exit_timestamp": leg.get("exit_timestamp"),
                "exit_open": leg.get("exit_open"),
                "realized_points": leg.get("realized_points"),
                "realized_return_pct": leg.get("realized_return_pct"),
                "issue": snapshot.get("issue"),
            }
        )
    return out


def replay_ce_shadow_from_directional_summary(
    *,
    directional_summary_path: str | Path =
        "data/historical-evidence/hilega-directional-replay-v1/multi-session-directional-summary.json",
    output_root: str | Path =
        "data/historical-evidence/hilega-directional-ce-shadow-v1",
    data_root: str | Path = "data",
    dates: Sequence[date] | None = None,
    expected_expiry: str | None = None,
    strike_step: float = 50.0,
) -> dict[str, Any]:
    """Project only coordinator-accepted bullish trades onto exact CE ATM±2 evidence.

    No strategy logic is rerun here. No option price is interpolated or synthesized.
    """
    directional_summary_path = Path(directional_summary_path)
    directional = json.loads(directional_summary_path.read_text(encoding="utf-8"))
    requested = {d.isoformat() for d in dates} if dates else None

    bullish = [
        trade for trade in directional.get("trades", [])
        if trade.get("direction") == "BULLISH"
        and (requested is None or trade.get("session_date") in requested)
    ]

    out_root = Path(output_root)
    out_root.mkdir(parents=True, exist_ok=True)

    all_trade_summaries: list[CETradeShadowSummary] = []
    all_legs: list[dict[str, Any]] = []
    session_cache: dict[str, OptionOHLCSesssion | Exception] = {}

    for trade_index, trade in enumerate(bullish, start=1):
        session_date = str(trade["session_date"])
        session_dir = out_root / session_date
        session_dir.mkdir(parents=True, exist_ok=True)

        if session_date not in session_cache:
            try:
                session_cache[session_date] = choose_option_ohlc_session(
                    session_date,
                    expected_expiry=expected_expiry,
                    data_root=data_root,
                )
            except Exception as exc:
                session_cache[session_date] = exc

        session = session_cache[session_date]
        if isinstance(session, Exception):
            all_trade_summaries.append(
                CETradeShadowSummary(
                    session_date=session_date,
                    trade_index=trade_index,
                    entry_time=str(trade["entry_time"]),
                    exit_time=str(trade["exit_time"]),
                    entry_event=str(trade["entry_event"]),
                    exit_event=str(trade["exit_event"]),
                    signal_spot=float(trade["entry_price"]),
                    atm=None,
                    expiry=None,
                    status="UNAVAILABLE",
                    complete_legs=0,
                    issue=f"OPTION_OHLC_UNAVAILABLE:{session}",
                )
            )
            continue

        expiry = date.fromisoformat(session.expiry)
        candidate_set = build_bullish_ce_candidate_set(
            signal_spot=float(trade["entry_price"]),
            expiry=expiry,
            contracts=_contracts(session),
            strike_step=strike_step,
            wings=2,
        )

        lifecycle = HilegaMilegaOptionShadowLifecycleV1()
        source = _option_source(session)
        entry_bar = _dt(session_date, str(trade["entry_time"]))
        snap = lifecycle.start(
            signal_bar_ts=entry_bar,
            signal_spot=float(trade["entry_price"]),
            source=str(trade["entry_event"]),
            candidate_set=candidate_set,
            option_minutes=source,
        )

        exit_bar = _dt(session_date, str(trade["exit_time"]))
        exit_boundary = exit_bar + timedelta(minutes=5)
        if snap.status == "ACTIVE":
            through = exit_boundary - timedelta(minutes=1)
            lifecycle.update(
                through_completed_minute=through,
                option_minutes=source,
            )
            snap = lifecycle.close(
                exit_boundary=exit_boundary,
                exit_reason=str(trade["exit_event"]),
                option_minutes=source,
            )

        payload = snap.payload()
        (session_dir / f"trade-{trade_index:03d}-ce-shadow.json").write_text(
            json.dumps(payload, indent=2) + "\n",
            encoding="utf-8",
        )

        legs = _leg_rows(
            session_date=session_date,
            trade_index=trade_index,
            snapshot=payload,
        )
        all_legs.extend(legs)

        complete_legs = sum(
            leg.get("entry_open") is not None and leg.get("exit_open") is not None
            for leg in payload.get("legs", [])
        )
        all_trade_summaries.append(
            CETradeShadowSummary(
                session_date=session_date,
                trade_index=trade_index,
                entry_time=str(trade["entry_time"]),
                exit_time=str(trade["exit_time"]),
                entry_event=str(trade["entry_event"]),
                exit_event=str(trade["exit_event"]),
                signal_spot=float(trade["entry_price"]),
                atm=float(payload["atm"]) if payload.get("atm") is not None else None,
                expiry=payload.get("expiry"),
                status=str(payload.get("status") or "INCOMPLETE"),
                complete_legs=complete_legs,
                issue=payload.get("issue"),
            )
        )

    summary_rows = [asdict(x) for x in all_trade_summaries]
    for session_date in sorted({x.session_date for x in all_trade_summaries}):
        session_rows = [x for x in summary_rows if x["session_date"] == session_date]
        session_legs = [x for x in all_legs if x["session_date"] == session_date]
        _write_csv(out_root / session_date / "ce-shadow-trades.csv", session_rows)
        _write_csv(out_root / session_date / "ce-shadow-legs.csv", session_legs)

    _write_csv(out_root / "multi-session-ce-shadow-trades.csv", summary_rows)
    _write_csv(out_root / "multi-session-ce-shadow-legs.csv", all_legs)

    status_counts: dict[str, int] = {}
    for row in summary_rows:
        status = str(row["status"])
        status_counts[status] = status_counts.get(status, 0) + 1

    result = {
        "model": MODEL,
        "status": "PASS",
        "directional_summary_path": str(directional_summary_path),
        "selection_policy": SELECTION_POLICY,
        "entry_semantics": ENTRY_SEMANTICS,
        "exit_semantics": EXIT_SEMANTICS,
        "observation_only": True,
        "execution_enabled": False,
        "paper_order_enabled": False,
        "option_selection_enabled": False,
        "quantity": None,
        "rupee_pnl_enabled": False,
        "nearest_minute_fallback": False,
        "nearest_strike_fallback": False,
        "bullish_trades_requested": len(bullish),
        "trade_status_counts": status_counts,
        "complete_closed_trades": sum(
            x.status == "CLOSED" and x.complete_legs == 5
            for x in all_trade_summaries
        ),
        "unavailable_trades": sum(
            x.status == "UNAVAILABLE" for x in all_trade_summaries
        ),
        "incomplete_trades": sum(
            x.status not in {"CLOSED", "UNAVAILABLE"} or
            (x.status == "CLOSED" and x.complete_legs != 5)
            for x in all_trade_summaries
        ),
        "trades": summary_rows,
        "manual_validation_required": True,
    }
    (out_root / "multi-session-ce-shadow-summary.json").write_text(
        json.dumps(result, indent=2) + "\n",
        encoding="utf-8",
    )
    return result
