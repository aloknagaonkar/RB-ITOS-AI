from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path

from .domain import IST


class HistoricalPositioningAdapterError(RuntimeError):
    pass


@dataclass(frozen=True)
class PositioningRow:
    session_date: str
    expiry: str
    timestamp: datetime
    spot: float
    moving_atm: float
    strike: float
    strike_offset: int
    ce_instrument_key: str
    pe_instrument_key: str
    ce_close: float | None
    pe_close: float | None
    ce_open_interest: int | None
    pe_open_interest: int | None
    ce_volume: int | None
    pe_volume: int | None


@dataclass(frozen=True)
class PositioningSession:
    source_path: str
    schema_version: int
    status: str
    underlying: str
    session_date: str
    expiry: str
    wings: int
    strike_interval: int
    rows: tuple[PositioningRow, ...]


def _parse_ts(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(IST)


def load_positioning_file(path: str | Path) -> PositioningSession:
    path = Path(path)
    payload = json.loads(path.read_text())

    if payload.get("status") != "AVAILABLE":
        raise HistoricalPositioningAdapterError(
            f"Positioning file not AVAILABLE: {path}"
        )

    required = (
        "schema_version",
        "underlying",
        "session_date",
        "expiry",
        "wings",
        "strike_interval",
        "rows",
    )
    missing = [key for key in required if key not in payload]
    if missing:
        raise HistoricalPositioningAdapterError(
            f"Missing keys {missing} in {path}"
        )

    rows: list[PositioningRow] = []
    for raw in payload["rows"]:
        rows.append(
            PositioningRow(
                session_date=str(raw["session_date"]),
                expiry=str(raw["expiry"]),
                timestamp=_parse_ts(str(raw["timestamp"])),
                spot=float(raw["spot"]),
                moving_atm=float(raw["moving_atm"]),
                strike=float(raw["strike"]),
                strike_offset=int(raw["strike_offset"]),
                ce_instrument_key=str(raw["ce_instrument_key"]),
                pe_instrument_key=str(raw["pe_instrument_key"]),
                ce_close=None if raw.get("ce_close") is None else float(raw["ce_close"]),
                pe_close=None if raw.get("pe_close") is None else float(raw["pe_close"]),
                ce_open_interest=None if raw.get("ce_open_interest") is None else int(raw["ce_open_interest"]),
                pe_open_interest=None if raw.get("pe_open_interest") is None else int(raw["pe_open_interest"]),
                ce_volume=None if raw.get("ce_volume") is None else int(raw["ce_volume"]),
                pe_volume=None if raw.get("pe_volume") is None else int(raw["pe_volume"]),
            )
        )

    declared = payload.get("row_count")
    if declared is not None and int(declared) != len(rows):
        raise HistoricalPositioningAdapterError(
            f"row_count={declared} but parsed {len(rows)} rows in {path}"
        )

    return PositioningSession(
        source_path=str(path),
        schema_version=int(payload["schema_version"]),
        status=str(payload["status"]),
        underlying=str(payload["underlying"]),
        session_date=str(payload["session_date"]),
        expiry=str(payload["expiry"]),
        wings=int(payload["wings"]),
        strike_interval=int(payload["strike_interval"]),
        rows=tuple(rows),
    )


def discover_positioning_sessions(
    *,
    data_root: str | Path = "data",
    session_date: str | None = None,
) -> list[Path]:
    root = Path(data_root)
    matches: list[Path] = []

    # Important: do not depend on exact cache filenames. Tests and future cache
    # writers may use different names. Directory + JSON content is authoritative.
    for directory in sorted(root.glob("historical-positioning-cache*")):
        if not directory.is_dir():
            continue

        for path in sorted(directory.glob("*.json")):
            if session_date is None:
                matches.append(path)
                continue

            try:
                payload = json.loads(path.read_text())
            except Exception:
                continue

            if payload.get("session_date") == session_date:
                matches.append(path)

    return matches


def choose_positioning_session(
    session_date: str,
    *,
    data_root: str | Path = "data",
) -> PositioningSession:
    candidates = discover_positioning_sessions(
        data_root=data_root,
        session_date=session_date,
    )

    if not candidates:
        raise HistoricalPositioningAdapterError(
            f"No historical positioning cache found for {session_date}"
        )

    target = date.fromisoformat(session_date)
    loaded: list[tuple[date, Path, PositioningSession]] = []

    for path in candidates:
        try:
            item = load_positioning_file(path)
        except Exception:
            continue

        expiry = date.fromisoformat(item.expiry)
        if expiry >= target:
            loaded.append((expiry, path, item))

    if not loaded:
        raise HistoricalPositioningAdapterError(
            f"No usable non-expired positioning cache found for {session_date}"
        )

    loaded.sort(key=lambda item: (item[0], str(item[1])))
    return loaded[0][2]


def timestamp_groups(session: PositioningSession) -> dict[datetime, list[PositioningRow]]:
    groups: dict[datetime, list[PositioningRow]] = {}
    for row in session.rows:
        groups.setdefault(row.timestamp, []).append(row)
    return dict(sorted(groups.items()))


def fixed_0920_rows(session: PositioningSession) -> list[PositioningRow]:
    for ts, rows in timestamp_groups(session).items():
        if ts.hour == 9 and ts.minute == 20:
            return rows

    raise HistoricalPositioningAdapterError(
        f"09:20 baseline unavailable in {session.source_path}"
    )
