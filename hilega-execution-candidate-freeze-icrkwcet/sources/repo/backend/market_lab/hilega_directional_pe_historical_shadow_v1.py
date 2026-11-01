from __future__ import annotations

import csv
import json
from dataclasses import asdict, dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Sequence

from .domain import IST
from .historical_option_ohlc_adapter_v1 import (
    HistoricalOptionOHLCError,
    OptionOHLCSesssion,
    choose_option_ohlc_session,
    instrument_candles,
)
from .hilega_milega_pe_option_candidate_v1 import build_bearish_pe_candidate_set
from .hilega_milega_pe_option_shadow_lifecycle_v1 import (
    HilegaMilegaPEOptionShadowLifecycleV1,
)

MODEL = "HILEGA_DIRECTIONAL_PE_ATM_PLUS_MINUS_2_HISTORICAL_SHADOW_V1"
SELECTION_POLICY = "ALL_ATM_PLUS_MINUS_2_PE_SHADOW"
ENTRY_SEMANTICS = "EXACT_1M_OPEN_AT_SIGNAL_BOUNDARY"
EXIT_SEMANTICS = "EXACT_1M_OPEN_AT_CAUSAL_EXIT_BOUNDARY"


@dataclass(frozen=True)
class PETradeShadowSummary:
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
        for k in row:
            if k not in seen:
                fields.append(k)
                seen.add(k)
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)


def _dt(session_date: str, hhmm: str) -> datetime:
    h, m = map(int, hhmm.split(":"))
    y, mo, d = map(int, session_date.split("-"))
    return datetime(y, mo, d, h, m, tzinfo=IST)


def _contracts(session: OptionOHLCSesssion) -> list[dict[str, Any]]:
    seen: set[tuple[str, float, str]] = set()
    rows: list[dict[str, Any]] = []
    for r in session.rows:
        ident = (r.instrument_key, float(r.strike), r.side.upper())
        if ident in seen:
            continue
        seen.add(ident)
        rows.append(
            {
                "instrument_key": r.instrument_key,
                "strike_price": float(r.strike),
                "side": r.side.upper(),
                "expiry": r.expiry,
            }
        )
    return rows


def _option_source(session: OptionOHLCSesssion):
    def source(instrument_key: str):
        return instrument_candles(session, instrument_key=instrument_key, side="PE")
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


def replay_pe_shadow_from_directional_summary(
    *,
    directional_summary_path: str | Path =
        "data/historical-evidence/hilega-directional-replay-v1/multi-session-directional-summary.json",
    output_root: str | Path =
        "data/historical-evidence/hilega-directional-pe-shadow-v1",
    data_root: str | Path = "data",
    dates: Sequence[date] | None = None,
    expected_expiry: str | None = None,
    strike_step: float = 50.0,
) -> dict[str, Any]:
    directional_summary_path = Path(directional_summary_path)
    directional = json.loads(directional_summary_path.read_text(encoding="utf-8"))
    requested = {d.isoformat() for d in dates} if dates else None

    bearish = [
        t for t in directional.get("trades", [])
        if t.get("direction") == "BEARISH"
        and (requested is None or t.get("session_date") in requested)
    ]

    out_root = Path(output_root)
    out_root.mkdir(parents=True, exist_ok=True)

    all_trade_summaries: list[PETradeShadowSummary] = []
    all_legs: list[dict[str, Any]] = []
    session_cache: dict[str, OptionOHLCSesssion | Exception] = {}

    for i, trade in enumerate(bearish, start=1):
        session_date = str(trade["session_date"])
        session_dir = out_root/session_date
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
                PETradeShadowSummary(
                    session_date=session_date,
                    trade_index=i,
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
        candidate_set = build_bearish_pe_candidate_set(
            signal_spot=float(trade["entry_price"]),
            expiry=expiry,
            contracts=_contracts(session),
            strike_step=strike_step,
            wings=2,
        )

        lifecycle = HilegaMilegaPEOptionShadowLifecycleV1()
        source = _option_source(session)
        entry_bar = _dt(session_date, str(trade["entry_time"]))
        snap = lifecycle.start(
            signal_bar_ts=entry_bar,
            signal_spot=float(trade["entry_price"]),
            source=str(trade["entry_event"]),
            candidate_set=candidate_set,
            option_minutes=source,
        )

        # Update only through the final fully completed option minute before the
        # exact exit boundary. Exit itself uses that boundary's exact OPEN.
        exit_bar = _dt(session_date, str(trade["exit_time"]))

        # Structural exit_time is the 5m signal-bar label, so the exact option
        # exit is the following 5m boundary OPEN.
        #
        # SESSION_CUTOFF_EXIT_1455_OPEN is different: its event semantics
        # explicitly require the 14:55 OPEN itself, never 15:00.
        # Both bullish and bearish cutoff events end with this semantic marker:
        #   SESSION_CUTOFF_EXIT_1455_OPEN
        #   BEARISH_SESSION_CUTOFF_EXIT_1455_OPEN
        # In both cases the exact option exit is the 14:55 OPEN itself.
        if str(trade["exit_event"]).endswith("SESSION_CUTOFF_EXIT_1455_OPEN"):
            exit_boundary = exit_bar
        else:
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
        trade_index = i
        per_trade_path = session_dir/f"trade-{trade_index:03d}-pe-shadow.json"
        per_trade_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")

        legs = _leg_rows(
            session_date=session_date,
            trade_index=trade_index,
            snapshot=payload,
        )
        all_legs.extend(legs)
        complete_legs = sum(
            x.get("entry_open") is not None and x.get("exit_open") is not None
            for x in payload.get("legs", [])
        )
        all_trade_summaries.append(
            PETradeShadowSummary(
                session_date=session_date,
                trade_index=trade_index,
                entry_time=str(trade["entry_time"]),
                exit_time=str(trade["exit_time"]),
                entry_event=str(trade["entry_event"]),
                exit_event=str(trade["exit_event"]),
                signal_spot=float(trade["entry_price"]),
                atm=float(payload["atm"]) if payload.get("atm") is not None else None,
                expiry=payload.get("expiry"),
                status=str(payload.get("status")),
                complete_legs=complete_legs,
                issue=payload.get("issue"),
            )
        )

    # Session-level files
    for sd in sorted({x.session_date for x in all_trade_summaries}):
        ts = [x for x in all_trade_summaries if x.session_date == sd]
        legs = [x for x in all_legs if x["session_date"] == sd]
        _write_csv(out_root/sd/"pe-shadow-trades.csv", [asdict(x) for x in ts])
        _write_csv(out_root/sd/"pe-shadow-legs.csv", legs)

    statuses: dict[str, int] = {}
    for t in all_trade_summaries:
        statuses[t.status] = statuses.get(t.status, 0) + 1

    summary = {
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
        "bearish_trades_requested": len(bearish),
        "trade_status_counts": statuses,
        "complete_closed_trades": sum(
            t.status == "CLOSED" and t.complete_legs == 5 for t in all_trade_summaries
        ),
        "unavailable_trades": sum(t.status == "UNAVAILABLE" for t in all_trade_summaries),
        "incomplete_trades": sum(
            t.status not in {"CLOSED", "UNAVAILABLE"} for t in all_trade_summaries
        ),
        "trades": [asdict(x) for x in all_trade_summaries],
        "manual_validation_required": True,
    }

    (out_root/"multi-session-pe-shadow-summary.json").write_text(
        json.dumps(summary, indent=2) + "\n", encoding="utf-8"
    )
    _write_csv(out_root/"multi-session-pe-shadow-trades.csv", [asdict(x) for x in all_trade_summaries])
    _write_csv(out_root/"multi-session-pe-shadow-legs.csv", all_legs)
    return summary
