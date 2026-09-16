from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Iterable

from .domain import IST


class HistoricalOptionOHLCError(RuntimeError):
    pass


@dataclass(frozen=True)
class OptionMinuteCandle:
    session_date: str
    expiry: str
    underlying: str
    instrument_key: str
    strike: float
    side: str
    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    volume: int
    open_interest: int
    provenance: str


@dataclass(frozen=True)
class OptionOHLCSesssion:
    source_path: str
    session_date: str
    expiry: str
    wings: int
    strike_interval: int
    rows: tuple[OptionMinuteCandle, ...]


def _parse_ts(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(IST)


def discover_option_ohlc_files(
    session_date: str,
    *,
    data_root: str | Path = "data",
) -> list[Path]:
    root = Path(data_root)
    matches: list[Path] = []

    for directory in sorted(root.glob("historical-option-ohlc-cache*")):
        if not directory.is_dir():
            continue
        for path in sorted(directory.glob("*.json")):
            try:
                payload = json.loads(path.read_text())
            except Exception:
                continue
            if (
                payload.get("status") == "AVAILABLE"
                and payload.get("session_date") == session_date
            ):
                matches.append(path)

    return matches


def load_option_ohlc_file(path: str | Path) -> OptionOHLCSesssion:
    path = Path(path)
    payload = json.loads(path.read_text())

    if payload.get("status") != "AVAILABLE":
        raise HistoricalOptionOHLCError(f"OHLC cache not AVAILABLE: {path}")

    required = {
        "session_date", "expiry", "wings", "strike_interval", "rows"
    }
    missing = required - set(payload)
    if missing:
        raise HistoricalOptionOHLCError(
            f"OHLC cache missing keys {sorted(missing)}: {path}"
        )

    rows: list[OptionMinuteCandle] = []
    for raw in payload["rows"]:
        rows.append(
            OptionMinuteCandle(
                session_date=str(raw["session_date"]),
                expiry=str(raw["expiry"]),
                underlying=str(raw["underlying"]),
                instrument_key=str(raw["instrument_key"]),
                strike=float(raw["strike"]),
                side=str(raw["side"]).upper(),
                timestamp=_parse_ts(str(raw["timestamp"])),
                open=float(raw["open"]),
                high=float(raw["high"]),
                low=float(raw["low"]),
                close=float(raw["close"]),
                volume=int(raw.get("volume") or 0),
                open_interest=int(raw.get("open_interest") or 0),
                provenance=str(raw.get("provenance") or ""),
            )
        )

    declared = payload.get("row_count")
    if declared is not None and int(declared) != len(rows):
        raise HistoricalOptionOHLCError(
            f"row_count={declared} but parsed {len(rows)} rows in {path}"
        )

    return OptionOHLCSesssion(
        source_path=str(path),
        session_date=str(payload["session_date"]),
        expiry=str(payload["expiry"]),
        wings=int(payload["wings"]),
        strike_interval=int(payload["strike_interval"]),
        rows=tuple(rows),
    )


def choose_option_ohlc_session(
    session_date: str,
    *,
    expected_expiry: str | None = None,
    data_root: str | Path = "data",
) -> OptionOHLCSesssion:
    candidates = discover_option_ohlc_files(
        session_date,
        data_root=data_root,
    )
    if not candidates:
        raise HistoricalOptionOHLCError(
            f"No historical option OHLC cache found for {session_date}"
        )

    loaded: list[OptionOHLCSesssion] = []
    for path in candidates:
        try:
            item = load_option_ohlc_file(path)
        except Exception:
            continue
        if expected_expiry is not None and item.expiry != expected_expiry:
            continue
        loaded.append(item)

    if not loaded:
        raise HistoricalOptionOHLCError(
            f"No usable option OHLC cache for {session_date}"
            + (
                f" expiry={expected_expiry}"
                if expected_expiry is not None
                else ""
            )
        )

    # Prefer the exact one-session cache when several overlapping caches exist.
    loaded.sort(
        key=lambda item: (
            0 if f"__{session_date}__" in Path(item.source_path).name else 1,
            len(item.rows),
            item.source_path,
        )
    )
    return loaded[0]


def instrument_candles(
    session: OptionOHLCSesssion,
    *,
    instrument_key: str,
    side: str,
) -> list[OptionMinuteCandle]:
    out = [
        row for row in session.rows
        if row.instrument_key == instrument_key and row.side == side.upper()
    ]
    return sorted(out, key=lambda row: row.timestamp)
