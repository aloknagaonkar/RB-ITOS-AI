from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Iterable


@dataclass(frozen=True)
class FixedStrikeOIRow:
    strike: float
    ce_open_interest: int
    pe_open_interest: int


class FixedStrikeOIFallbackError(RuntimeError):
    pass


def _parse_ts(value: str) -> datetime:
    return datetime.fromisoformat(str(value).replace("Z", "+00:00"))


def choose_option_ohlc_json(
    session_date: str,
    *,
    data_root: str | Path = "data",
) -> Path:
    root = Path(data_root)
    allowed = ("train", "oos-a", "oos-b", "oos-c", "oos-d")

    exact_candidates: list[Path] = []
    for bucket in allowed:
        directory = root / f"historical-option-ohlc-cache-{bucket}"
        if not directory.exists():
            continue
        exact_candidates.extend(
            sorted(directory.glob(f"*__{session_date}__{session_date}__*.json"))
        )

    if exact_candidates:
        return exact_candidates[0]

    for bucket in allowed:
        directory = root / f"historical-option-ohlc-cache-{bucket}"
        if not directory.exists():
            continue
        for path in sorted(directory.glob(f"*{session_date}*.json")):
            try:
                payload = json.loads(path.read_text())
            except Exception:
                continue
            if (
                payload.get("status") == "AVAILABLE"
                and str(payload.get("session_date")) == session_date
            ):
                return path

    raise FixedStrikeOIFallbackError(
        f"No option OHLC cache found for {session_date}"
    )


def load_option_oi_index(
    session_date: str,
    *,
    data_root: str | Path = "data",
) -> tuple[Path, dict[tuple[datetime, float], FixedStrikeOIRow]]:
    path = choose_option_ohlc_json(session_date, data_root=data_root)
    payload = json.loads(path.read_text())

    if payload.get("status") != "AVAILABLE":
        raise FixedStrikeOIFallbackError(
            f"Option OHLC cache is not AVAILABLE: {path}"
        )

    per_side: dict[tuple[datetime, float], dict[str, int]] = {}

    for row in payload.get("rows") or []:
        raw_ts = row.get("timestamp")
        raw_strike = row.get("strike")
        side = str(row.get("side") or "").upper()
        raw_oi = row.get("open_interest")

        if (
            raw_ts is None
            or raw_strike is None
            or raw_oi is None
            or side not in {"CE", "PE"}
        ):
            continue

        ts = _parse_ts(raw_ts)
        if ts.date().isoformat() != session_date:
            continue

        key = (ts, float(raw_strike))
        bucket = per_side.setdefault(key, {})
        if side in bucket:
            raise FixedStrikeOIFallbackError(
                f"Duplicate {side} OI for {ts.isoformat()} strike={raw_strike}"
            )
        bucket[side] = int(raw_oi)

    out: dict[tuple[datetime, float], FixedStrikeOIRow] = {}
    for key, sides in per_side.items():
        if "CE" in sides and "PE" in sides:
            out[key] = FixedStrikeOIRow(
                strike=key[1],
                ce_open_interest=sides["CE"],
                pe_open_interest=sides["PE"],
            )

    return path, out


def select_exact_strikes_with_oi_fallback(
    rows: Iterable,
    strikes: Iterable[float],
    *,
    timestamp: datetime,
    option_oi_index: dict[tuple[datetime, float], FixedStrikeOIRow],
):
    by = {float(row.strike): row for row in rows}
    selected = []
    missing = []

    for strike in strikes:
        key = float(strike)
        row = by.get(key)
        if row is not None:
            selected.append(row)
            continue

        fallback = option_oi_index.get((timestamp, key))
        if fallback is None:
            missing.append(key)
        else:
            selected.append(fallback)

    if missing:
        raise FixedStrikeOIFallbackError(
            f"Missing exact strikes after option-OHLC OI fallback: {missing}"
        )

    return selected
