from __future__ import annotations

import json
import copy
import hashlib
from functools import lru_cache
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from fastapi import APIRouter, HTTPException, Query

from .live_shadow_step_audit_v1 import ShadowStepAuditStoreV1
from .domain import HistoricalCandle
from .hilega_market_evidence_v1 import canonical, verify_journal
from .hilega_milega_historical_replay_v1 import aggregate_exact_5m
from .hilega_milega_live_shadow_v1 import (
    completed_intraday_1m_for_label,
    latest_completed_5m_label,
)
from .hilega_milega_strategy_v1 import HilegaMilegaIndicatorEngineV1

router = APIRouter(
    prefix="/api/live-shadow/hilega-directional-candles",
    tags=["hilega-directional-candles"],
)

IST = ZoneInfo("Asia/Kolkata")
HIST_ROOT = Path("data/historical-evidence/hilega-directional-replay-v1")
LIVE_BULLISH_AUDIT = Path("data/live-observation/hilega-milega-v1/step-audit.jsonl")
LIVE_DIRECTIONAL_AUDIT = Path("data/live-observation/hilega-directional-v1/step-audit.jsonl")

LIVE_DIRECTIONAL_EVIDENCE_ROOT = Path(
    "data/live-observation/"
    "hilega-directional-market-evidence-v1"
)

UNDERLYING_CACHE_ROOT = Path(
    "data/historical-evidence/"
    "hilega-milega-underlying-cache-v1"
)

LIVE_UI_WARMUP_CALENDAR_DAYS = 45


def _iso_session(value: Any) -> str | None:
    if not isinstance(value, str) or len(value) < 10:
        return None
    head = value[:10]
    try:
        datetime.strptime(head, "%Y-%m-%d")
    except ValueError:
        return None
    return head


def _hhmm(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if dt.tzinfo is not None:
            dt = dt.astimezone(IST)
        return dt.strftime("%H:%M")
    except ValueError:
        return value[:5] if len(value) >= 5 and value[2:3] == ":" else None


def _read_audit(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    store = ShadowStepAuditStoreV1(path)
    try:
        return store.read_all()
    except Exception:
        return []


def _timestamp(row: dict[str, Any]) -> str | None:
    payload = row.get("payload") or {}
    for value in (
        payload.get("bar_timestamp"),
        payload.get("signal_bar"),
        row.get("checkpoint"),
    ):
        if isinstance(value, str):
            return value
    return None


def _action_from_directional(payload: dict[str, Any]) -> str:
    accepted = [str(x) for x in (payload.get("accepted_events") or [])]
    joined = "|".join(accepted)
    before = str(payload.get("trade_owner_before") or payload.get("owner_before") or "NONE")
    after = str(payload.get("trade_owner_after") or payload.get("owner_after") or "NONE")

    if any(
        x.startswith("ENTRY_BEARISH")
        or x == "ENTRY_OPENING_BEARISH_CONFIRMED"
        for x in accepted
    ):
        return "BEARISH_ENTRY"

    if any(
        x.startswith("ENTRY_")
        and not x.startswith("ENTRY_BEARISH")
        and x != "ENTRY_OPENING_BEARISH_CONFIRMED"
        for x in accepted
    ):
        return "BULLISH_ENTRY"
    if "STRUCTURAL_EXIT_BEARISH" in joined or "BEARISH_SESSION_CUTOFF_EXIT" in joined:
        return "BEARISH_EXIT"
    if "STRUCTURAL_EXIT_RSI_CROSS_BELOW_WMA21" in joined or "SESSION_CUTOFF_EXIT_1455_OPEN" in joined:
        if before == "BULLISH":
            return "BULLISH_EXIT"
    if before != after and after == "NONE":
        return f"{before}_EXIT" if before in {"BULLISH", "BEARISH"} else "EXIT"
    if after == "BULLISH":
        return "BULLISH_ACTIVE"
    if after == "BEARISH":
        return "BEARISH_ACTIVE"
    if payload.get("bullish_armed") or payload.get("bearish_armed"):
        return "ARMED_INFORMATION"
    return "NO_ACTION"


def _base_live_rows_legacy(session_date: str) -> dict[str, dict[str, Any]]:
    merged: dict[str, dict[str, Any]] = {}
    for record in _read_audit(LIVE_BULLISH_AUDIT):
        ts = _timestamp(record)
        if not ts or _iso_session(ts) != session_date:
            continue
        payload = record.get("payload") or {}
        stage = str(record.get("stage") or "")
        if stage not in {
            "UNDERLYING_5M_BUILD",
            "INDICATOR_CALCULATION",
            "STRATEGY_DECISION_RESULT",
            "STRATEGY_TRANSITION",
        }:
            continue
        row = merged.setdefault(ts, {
            "session_date": session_date,
            "time": _hhmm(ts),
            "bar_timestamp": ts,
            "open": None, "high": None, "low": None, "close": None, "volume": None,
            "rsi9": None, "ema3_rsi": None, "wma21_rsi": None,
            "owner_before": None, "owner_after": None,
            "bullish_state": None, "bearish_state": None,
            "bullish_armed": None, "bearish_armed": None,
            "action": "NO_DIRECTIONAL_AUDIT",
            "accepted_events": "",
            "suppressed_events": "",
            "note": "Directional state unavailable for this candle",
            "directional_evidence": False,
        })
        for key in ("open", "high", "low", "close", "volume", "rsi9", "ema3_rsi", "wma21_rsi"):
            if payload.get(key) is not None:
                row[key] = payload.get(key)

    return merged



def _cache_rows_for_day(day: str) -> list[HistoricalCandle]:
    """Read one canonical cached underlying 1m session.

    Historical cache rows may omit provider/instrument/session metadata
    because those values are stored once at the top level of the cache file.
    Rehydrate them here for HistoricalCandle validation.

    Read-only UI reconstruction; never calls the broker.
    """
    path = UNDERLYING_CACHE_ROOT / f"{day}.json"

    if not path.is_file():
        return []

    raw = json.loads(
        path.read_text(encoding="utf-8")
    )

    if isinstance(raw, list):
        rows = raw
        cache_session = day
        cache_underlying = "NSE_INDEX|Nifty 50"

    elif isinstance(raw, dict):
        cache_session = str(
            raw.get("session_date") or day
        )

        cache_underlying = str(
            raw.get("underlying")
            or "NSE_INDEX|Nifty 50"
        )

        rows = None

        for key in (
            "candles",
            "rows",
            "data",
        ):
            value = raw.get(key)

            if isinstance(value, list):
                rows = value
                break

        if rows is None:
            raise ValueError(
                f"UNSUPPORTED_UNDERLYING_CACHE_SHAPE:{path}"
            )

    else:
        raise ValueError(
            f"UNSUPPORTED_UNDERLYING_CACHE_TYPE:{path}"
        )

    out = []

    for r in rows:
        if not isinstance(r, dict):
            raise ValueError(
                f"INVALID_UNDERLYING_CACHE_ROW:{path}"
            )

        enriched = dict(r)

        if enriched.get("provider") in (
            None,
            "",
        ):
            enriched["provider"] = "upstox"

        if enriched.get("instrument_key") in (
            None,
            "",
        ):
            enriched["instrument_key"] = (
                cache_underlying
            )

        if enriched.get("session_date") in (
            None,
            "",
        ):
            enriched["session_date"] = (
                cache_session
            )

        out.append(
            HistoricalCandle.model_validate(
                enriched
            )
        )

    return out

def _latest_directional_underlying(
    session_date: str,
    *, fast: bool = False,
) -> tuple[datetime, list[HistoricalCandle]] | None:

    path = (
        LIVE_DIRECTIONAL_EVIDENCE_ROOT
        / f"{session_date}.jsonl"
    )

    if not path.is_file():
        return None

    rows = _recent_underlying_records(path) if fast else verify_journal(path)

    candidates = [
        r
        for r in rows
        if (
            r.get("kind") == "underlying"
            and r.get("status") == "OK"
            and isinstance(r.get("response"), list)
        )
    ]

    if not candidates:
        return None

    latest = candidates[-1]

    args = latest.get("args") or {}
    now_value = args.get("now")

    if not isinstance(now_value, str):
        return None

    acquired_now = datetime.fromisoformat(
        now_value.replace("Z", "+00:00")
    ).astimezone(IST)

    candles = [
        HistoricalCandle.model_validate(r)
        for r in latest["response"]
    ]

    return acquired_now, candles


def _recent_underlying_records(path: Path) -> list[dict[str, Any]]:
    """Read a bounded journal tail for display; full chain verification is separate."""
    with path.open("rb") as handle:
        handle.seek(0, 2)
        size = handle.tell()
        start = max(0, size - 16 * 1024 * 1024)
        handle.seek(start)
        raw = handle.read()
    lines = raw.splitlines()
    if start:
        lines = lines[1:]
    wanted = None
    selected = None
    for line in reversed(lines):
        try:
            row = json.loads(line)
        except (ValueError, UnicodeDecodeError):
            continue
        if row.get("kind") != "underlying" or row.get("status") != "OK":
            continue
        body = {k: v for k, v in row.items() if k != "record_hash"}
        if hashlib.sha256(canonical(body)).hexdigest() != row.get("record_hash"):
            continue
        if selected is None:
            selected = row
            if isinstance(row.get("response"), list):
                return [row]
            wanted = row.get("response_ref")
        elif wanted and isinstance(row.get("response"), list):
            if hashlib.sha256(canonical(row["response"])).hexdigest() == wanted:
                selected["response"] = row["response"]
                return [selected]
    return []


def _directional_evidence_live_rows(
    session_date: str,
    *, fast: bool = False,
) -> dict[str, dict[str, Any]]:
    """Reconstruct live OHLC + indicators from directional evidence.

    This is read-only UI reconstruction. It does not mutate live strategy
    state and never calls the broker.
    """

    source = _latest_directional_underlying(
        session_date, fast=fast
    )

    if source is None:
        return {}

    acquired_now, intraday = source

    day = datetime.strptime(
        session_date,
        "%Y-%m-%d",
    ).date()

    if acquired_now.date() != day:
        return {}

    # Match the live worker: only completed 5m bars.
    target = latest_completed_5m_label(
        acquired_now
    )

    completed = completed_intraday_1m_for_label(
        intraday,
        target,
    )

    current_bars = aggregate_exact_5m(
        completed,
        day,
    )

    # Match live bootstrap indicator warm-up:
    # previous 45 calendar days, indicator history continuous.
    indicators = _warmup_indicators(day)

    merged: dict[str, dict[str, Any]] = {}

    for bar in current_bars:

        ind = indicators.update(
            bar.close
        )

        ts = bar.ts.isoformat()

        merged[ts] = {
            "session_date": session_date,
            "time": bar.ts.astimezone(IST).strftime("%H:%M"),
            "bar_timestamp": ts,
            "open": float(bar.open),
            "high": float(bar.high),
            "low": float(bar.low),
            "close": float(bar.close),
            "volume": int(bar.volume or 0),
            "rsi9": ind.rsi9,
            "ema3_rsi": ind.ema3_rsi,
            "wma21_rsi": ind.wma21_rsi,
            "owner_before": None,
            "owner_after": None,
            "bullish_state": None,
            "bearish_state": None,
            "bullish_armed": None,
            "bearish_armed": None,
            "action": "NO_DIRECTIONAL_AUDIT",
            "accepted_events": "",
            "suppressed_events": "",
            "note": "Directional state unavailable for this candle",
            "directional_evidence": False,
        }

    return merged


def _warmup_indicators(day):
    paths = [UNDERLYING_CACHE_ROOT / f"{(day - timedelta(days=i)).isoformat()}.json"
             for i in range(1, LIVE_UI_WARMUP_CALENDAR_DAYS + 1)]
    signature = tuple((p.name, p.stat().st_size, p.stat().st_mtime_ns) for p in paths if p.is_file())
    return copy.deepcopy(_cached_warmup(day.isoformat(), str(UNDERLYING_CACHE_ROOT), signature))


@lru_cache(maxsize=8)
def _cached_warmup(day_string: str, cache_root: str, signature: tuple) -> HilegaMilegaIndicatorEngineV1:
    day = datetime.strptime(day_string, "%Y-%m-%d").date()
    indicators = HilegaMilegaIndicatorEngineV1()

    d = day - timedelta(
        days=LIVE_UI_WARMUP_CALENDAR_DAYS
    )

    while d < day:

        cached = _cache_rows_for_day(
            d.isoformat()
        )

        if cached:
            for bar in aggregate_exact_5m(
                cached,
                d,
            ):
                indicators.update(
                    bar.close
                )

        d += timedelta(days=1)

    return indicators


def _base_live_rows(
    session_date: str,
) -> dict[str, dict[str, Any]]:
    """Prefer directional evidence; retain legacy audit fallback."""

    try:
        rows = _directional_evidence_live_rows(
            session_date
        )

        if rows:
            return rows

    except Exception:
        # Preserve prior UI behavior if reconstruction evidence
        # is temporarily unavailable. Never affect live strategy.
        pass

    return _base_live_rows_legacy(
        session_date
    )

def _latest_live_session() -> str | None:
    sessions: list[str] = []
    for path in (LIVE_BULLISH_AUDIT, LIVE_DIRECTIONAL_AUDIT):
        for record in _read_audit(path):
            ts = _timestamp(record)
            session = _iso_session(ts)
            if session:
                sessions.append(session)
            payload = record.get("payload") or {}
            for key in ("last_completed_bar", "cutoff_timestamp"):
                session = _iso_session(payload.get(key))
                if session:
                    sessions.append(session)
    return max(sessions) if sessions else None


def build_live_directional_candles(session_date: str | None = None, *, audit_only: bool = False) -> dict[str, Any]:
    day = session_date or _latest_live_session()
    if not day:
        return {
            "model": "HILEGA_DIRECTIONAL_CANDLE_UI_V1",
            "mode": "LIVE",
            "session_date": None,
            "row_count": 0,
            "directional_row_count": 0,
            "rows": [],
            "warning": "No current live candle evidence is available.",
        }

    if audit_only:
        try:
            rows = _directional_evidence_live_rows(day, fast=True)
        except Exception:
            rows = {}
        if not rows:
            rows = _base_live_rows_legacy(day)
    else:
        rows = _base_live_rows(day)
    directional_count = 0

    for record in _read_audit(LIVE_DIRECTIONAL_AUDIT):
        if record.get("stage") != "DIRECTIONAL_DECISION":
            continue
        payload = record.get("payload") or {}
        ts = payload.get("bar_timestamp") or record.get("checkpoint")
        if not isinstance(ts, str) or _iso_session(ts) != day:
            continue

        row = rows.setdefault(ts, {
            "session_date": day,
            "time": _hhmm(ts),
            "bar_timestamp": ts,
            "open": None, "high": None, "low": None, "close": None, "volume": None,
            "rsi9": None, "ema3_rsi": None, "wma21_rsi": None,
        })
        row.update({
            "owner_before": payload.get("trade_owner_before"),
            "owner_after": payload.get("trade_owner_after"),
            "bullish_state": payload.get("bullish_state"),
            "bearish_state": payload.get("bearish_state"),
            "bullish_armed": payload.get("bullish_armed"),
            "bearish_armed": payload.get("bearish_armed"),
            "action": _action_from_directional(payload),
            "accepted_events": ",".join(str(x) for x in (payload.get("accepted_events") or [])),
            "suppressed_events": ",".join(str(x) for x in (payload.get("suppressed_events") or [])),
            "note": payload.get("note"),
            "directional_evidence": True,
        })
        directional_count += 1

    ordered = [rows[key] for key in sorted(rows)]
    return {
        "model": "HILEGA_DIRECTIONAL_CANDLE_UI_V1",
        "mode": "LIVE",
        "session_date": day,
        "row_count": len(ordered),
        "directional_row_count": directional_count,
        "rows": ordered,
        "warning": (
            "Fast view from recorded underlying snapshot; full journal chain verification was deferred. "
            "Directional state is overlaid only where an exact audit bar exists."
            if audit_only else
            "Candle/indicator evidence is shown for the current live session. "
            "Directional state is overlaid only where the directional audit contains "
            "that exact bar; earlier bars are not retroactively invented."
        ),
    }


def build_historical_directional_candles(session_date: str) -> dict[str, Any]:
    try:
        datetime.strptime(session_date, "%Y-%m-%d")
    except ValueError as exc:
        raise HTTPException(400, "session_date must be YYYY-MM-DD") from exc

    path = HIST_ROOT / session_date / "directional-candle-by-candle.json"
    if not path.is_file():
        live = build_live_directional_candles(session_date)
        if live.get("rows"):
            return {
                **live,
                "mode": "HISTORICAL_LIVE_CAPTURE",
                "warning": (
                    "Historical view reconstructed from immutable directional live "
                    "audit/evidence for this session. No broker call or synthetic "
                    "strategy decision was made."
                ),
            }
        raise HTTPException(404, f"No directional candle replay evidence for {session_date}.")

    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, list):
        raise HTTPException(422, "Directional candle replay must be a JSON list.")

    return {
        "model": "HILEGA_DIRECTIONAL_CANDLE_UI_V1",
        "mode": "HISTORICAL_REPLAY",
        "session_date": session_date,
        "row_count": len(data),
        "directional_row_count": len(data),
        "rows": data,
        "warning": (
            "Historical rows come directly from the recorded directional "
            "candle-by-candle replay; bullish and bearish states are both preserved."
        ),
    }


@router.get("/historical")
def historical(session_date: str = Query(..., pattern=r"^\d{4}-\d{2}-\d{2}$")):
    return build_historical_directional_candles(session_date)


@router.get("/live")
def live(session_date: str | None = Query(None, pattern=r"^\d{4}-\d{2}-\d{2}$"), audit_only: bool = False):
    return build_live_directional_candles(session_date, audit_only=audit_only)
