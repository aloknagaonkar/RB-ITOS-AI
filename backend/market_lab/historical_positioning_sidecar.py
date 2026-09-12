"""Historical per-strike positioning sidecar.

This module intentionally does not change HistoricalResearchSession or its cache schema.
It reconstructs the option candles again, calculates same-instrument exact-time 5m/15m/30m
positioning, and writes a separate cache/output that can later be joined to frozen PCR events.
"""
from __future__ import annotations

import argparse
import csv
import json
import os
from dataclasses import asdict, dataclass
from datetime import date, datetime, time
from pathlib import Path
from typing import Iterable, Literal, Protocol, Sequence

from .domain import (
    HistoricalCandle,
    HistoricalOptionCandleSeries,
    HistoricalOptionContract,
    HistoricalReconstructedSnapshot,
    IST,
)
from .historical import (
    load_historical_option_candles,
    reconstruct_historical_snapshots,
    resolve_historical_atm,
    resolve_historical_option_contracts,
)
from .historical_positioning import (
    CombinedStrikeObservation,
    PositioningConfig,
    PositioningState,
    SidePoint,
    build_positioning_index,
    build_strike_positioning,
)

PROVENANCE = "HISTORICAL_CANDLE_RECONSTRUCTION"
SCHEMA_VERSION = 1
DEFAULT_HORIZONS = (5, 15, 30)


class HistoricalPositioningGateway(Protocol):
    def historical_candles(self, instrument_key: str, session_date: date) -> list[HistoricalCandle]: ...
    def historical_option_contracts(self, underlying: str, expiry: date) -> list[HistoricalOptionContract]: ...
    def historical_option_candles(self, instrument_key: str, session_date: date) -> list[HistoricalCandle]: ...


@dataclass(frozen=True)
class HistoricalPositioningRow:
    session_date: date
    expiry: date
    timestamp: datetime
    underlying: str
    spot: float
    moving_atm: float
    strike: float
    strike_offset: int
    ce_instrument_key: str | None
    pe_instrument_key: str | None
    ce_close: float | None
    pe_close: float | None
    ce_open_interest: float | None
    pe_open_interest: float | None
    ce_volume: int | None
    pe_volume: int | None
    ce_5m_premium_change_pct: float | None
    ce_5m_oi_change_pct: float | None
    ce_5m_state: str
    pe_5m_premium_change_pct: float | None
    pe_5m_oi_change_pct: float | None
    pe_5m_state: str
    combined_5m: str
    ce_15m_premium_change_pct: float | None
    ce_15m_oi_change_pct: float | None
    ce_15m_state: str
    pe_15m_premium_change_pct: float | None
    pe_15m_oi_change_pct: float | None
    pe_15m_state: str
    combined_15m: str
    ce_30m_premium_change_pct: float | None
    ce_30m_oi_change_pct: float | None
    ce_30m_state: str
    pe_30m_premium_change_pct: float | None
    pe_30m_oi_change_pct: float | None
    pe_30m_state: str
    combined_30m: str
    provenance: str = PROVENANCE


@dataclass(frozen=True)
class HistoricalPositioningSession:
    schema_version: int
    status: Literal["AVAILABLE", "UNAVAILABLE"]
    underlying: str
    session_date: date
    expiry: date
    wings: int
    strike_interval: int
    row_count: int
    rows: tuple[HistoricalPositioningRow, ...]
    issues: tuple[str, ...]
    provenance: str = PROVENANCE


def _side_point(snapshot: HistoricalReconstructedSnapshot, strike: float, side_name: str) -> SidePoint | None:
    row = next((item for item in snapshot.strikes if item.strike == strike), None)
    if row is None:
        return None
    side = row.ce if side_name == "CE" else row.pe
    if side.instrument_key is None:
        return None
    return SidePoint(
        timestamp=snapshot.timestamp,
        instrument_key=side.instrument_key,
        strike=strike,
        side=side_name,
        close=side.close,
        open_interest=side.open_interest,
    )


def _all_series_points(series: Iterable[HistoricalOptionCandleSeries]) -> list[SidePoint]:
    points: list[SidePoint] = []
    for item in series:
        for candle in item.candles:
            points.append(SidePoint(
                timestamp=candle.timestamp,
                instrument_key=item.contract.instrument_key,
                strike=item.contract.strike,
                side=item.contract.side,
                close=candle.close,
                open_interest=candle.open_interest,
            ))
    return points


def _strike_offset(strike: float, atm: float, strike_interval: int) -> int:
    raw = (strike - atm) / strike_interval
    rounded = int(round(raw))
    if abs(raw - rounded) > 1e-9:
        raise ValueError("strike is not aligned with moving ATM interval")
    return rounded


def _empty_horizon() -> dict[str, object]:
    return {
        "ce_premium": None, "ce_oi": None, "ce_state": PositioningState.UNAVAILABLE.value,
        "pe_premium": None, "pe_oi": None, "pe_state": PositioningState.UNAVAILABLE.value,
        "combined": CombinedStrikeObservation.UNAVAILABLE.value,
    }


def build_positioning_rows_from_reconstruction(
    *,
    snapshots: Sequence[HistoricalReconstructedSnapshot],
    option_series: Sequence[HistoricalOptionCandleSeries],
    horizons: Sequence[int] = DEFAULT_HORIZONS,
    config: PositioningConfig = PositioningConfig(),
) -> list[HistoricalPositioningRow]:
    """Build wide per-strike sidecar rows using exact same-instrument historical baselines."""
    if tuple(horizons) != DEFAULT_HORIZONS:
        raise ValueError("v1 sidecar requires horizons 5, 15 and 30 minutes")
    points = _all_series_points(option_series)
    index = build_positioning_index(points)
    rows: list[HistoricalPositioningRow] = []

    for snapshot in sorted(snapshots, key=lambda item: item.timestamp):
        strike_map = {row.strike: row for row in snapshot.strikes}
        for strike in sorted(strike_map):
            source = strike_map[strike]
            ce_current = _side_point(snapshot, strike, "CE")
            pe_current = _side_point(snapshot, strike, "PE")
            by_horizon: dict[int, dict[str, object]] = {}
            for horizon in horizons:
                if ce_current is None or pe_current is None:
                    by_horizon[horizon] = _empty_horizon()
                    continue
                result = build_strike_positioning(
                    ce_current=ce_current,
                    pe_current=pe_current,
                    horizon_minutes=horizon,
                    index=index,
                    config=config,
                )
                by_horizon[horizon] = {
                    "ce_premium": result.ce.premium_change_pct,
                    "ce_oi": result.ce.oi_change_pct,
                    "ce_state": result.ce.state.value,
                    "pe_premium": result.pe.premium_change_pct,
                    "pe_oi": result.pe.oi_change_pct,
                    "pe_state": result.pe.state.value,
                    "combined": result.combined.value,
                }

            h5, h15, h30 = by_horizon[5], by_horizon[15], by_horizon[30]
            rows.append(HistoricalPositioningRow(
                session_date=snapshot.session_date,
                expiry=snapshot.expiry,
                timestamp=snapshot.timestamp,
                underlying=snapshot.underlying,
                spot=snapshot.spot,
                moving_atm=snapshot.moving_atm,
                strike=strike,
                strike_offset=_strike_offset(strike, snapshot.moving_atm, snapshot.strike_interval),
                ce_instrument_key=source.ce.instrument_key,
                pe_instrument_key=source.pe.instrument_key,
                ce_close=source.ce.close,
                pe_close=source.pe.close,
                ce_open_interest=source.ce.open_interest,
                pe_open_interest=source.pe.open_interest,
                ce_volume=source.ce.volume,
                pe_volume=source.pe.volume,
                ce_5m_premium_change_pct=h5["ce_premium"], ce_5m_oi_change_pct=h5["ce_oi"], ce_5m_state=h5["ce_state"],
                pe_5m_premium_change_pct=h5["pe_premium"], pe_5m_oi_change_pct=h5["pe_oi"], pe_5m_state=h5["pe_state"], combined_5m=h5["combined"],
                ce_15m_premium_change_pct=h15["ce_premium"], ce_15m_oi_change_pct=h15["ce_oi"], ce_15m_state=h15["ce_state"],
                pe_15m_premium_change_pct=h15["pe_premium"], pe_15m_oi_change_pct=h15["pe_oi"], pe_15m_state=h15["pe_state"], combined_15m=h15["combined"],
                ce_30m_premium_change_pct=h30["ce_premium"], ce_30m_oi_change_pct=h30["ce_oi"], ce_30m_state=h30["ce_state"],
                pe_30m_premium_change_pct=h30["pe_premium"], pe_30m_oi_change_pct=h30["pe_oi"], pe_30m_state=h30["pe_state"], combined_30m=h30["combined"],
            ))
    return rows


def reconstruct_positioning_session(
    gateway: HistoricalPositioningGateway,
    underlying: str,
    session_date: date,
    expiry: date,
    wings: int,
    strike_interval: int = 50,
    fixed_anchor_time: time = time(9, 20),
    config: PositioningConfig = PositioningConfig(),
) -> HistoricalPositioningSession:
    """Fetch/reconstruct a sidecar session without touching PCR research caches."""
    underlying_candles = sorted(gateway.historical_candles(underlying, session_date), key=lambda c: c.timestamp)
    if not underlying_candles:
        return HistoricalPositioningSession(SCHEMA_VERSION, "UNAVAILABLE", underlying, session_date, expiry, wings, strike_interval, 0, (), ("underlying_candles_unavailable",))

    atms = resolve_historical_atm(underlying_candles, strike_interval)
    anchor = next((c for c in underlying_candles if c.timestamp.astimezone(IST).time().replace(tzinfo=None) == fixed_anchor_time), None)
    fixed_atm = resolve_historical_atm([anchor], strike_interval)[0].atm if anchor is not None else None
    required_atms = {item.atm for item in atms}
    if fixed_atm is not None:
        required_atms.add(fixed_atm)

    catalog = gateway.historical_option_contracts(underlying, expiry)
    selected_by_identity: dict[tuple[float, str], HistoricalOptionContract] = {}
    for atm in sorted(required_atms):
        for contract in resolve_historical_option_contracts(catalog, underlying, expiry, atm, wings, strike_interval):
            identity = (contract.strike, contract.side)
            existing = selected_by_identity.get(identity)
            if existing is not None and existing != contract:
                raise ValueError("Conflicting historical option contract identity")
            selected_by_identity[identity] = contract
    selected = sorted(selected_by_identity.values(), key=lambda c: (c.strike, 0 if c.side == "CE" else 1))
    option_series = load_historical_option_candles(gateway, selected, session_date)
    snapshots = reconstruct_historical_snapshots(
        underlying_candles, selected, option_series, underlying, expiry, session_date,
        wings, strike_interval, fixed_anchor_time=fixed_anchor_time,
    )
    rows = build_positioning_rows_from_reconstruction(snapshots=snapshots, option_series=option_series, config=config)
    return HistoricalPositioningSession(SCHEMA_VERSION, "AVAILABLE", underlying, session_date, expiry, wings, strike_interval, len(rows), tuple(rows), ())


def _jsonable(value):
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, tuple):
        return [_jsonable(v) for v in value]
    if isinstance(value, list):
        return [_jsonable(v) for v in value]
    if isinstance(value, dict):
        return {k: _jsonable(v) for k, v in value.items()}
    return value


def session_to_dict(session: HistoricalPositioningSession) -> dict:
    return _jsonable(asdict(session))


def _cache_path(cache_dir: str | Path, underlying: str, session_date: date, expiry: date, wings: int) -> Path:
    safe_underlying = underlying.replace("|", "_").replace("/", "_").replace(" ", "_")
    return Path(cache_dir) / f"{safe_underlying}__{session_date.isoformat()}__{expiry.isoformat()}__w{wings}.json"


def store_session_cache(cache_dir: str | Path, session: HistoricalPositioningSession) -> Path:
    path = _cache_path(cache_dir, session.underlying, session.session_date, session.expiry, session.wings)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(session_to_dict(session), indent=2) + "\n", encoding="utf-8")
    return path


def load_session_cache(cache_dir: str | Path, underlying: str, session_date: date, expiry: date, wings: int) -> HistoricalPositioningSession | None:
    path = _cache_path(cache_dir, underlying, session_date, expiry, wings)
    if not path.exists():
        return None
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("schema_version") != SCHEMA_VERSION:
        return None
    rows = []
    for raw in data["rows"]:
        raw = dict(raw)
        raw["session_date"] = date.fromisoformat(raw["session_date"])
        raw["expiry"] = date.fromisoformat(raw["expiry"])
        raw["timestamp"] = datetime.fromisoformat(raw["timestamp"])
        rows.append(HistoricalPositioningRow(**raw))
    return HistoricalPositioningSession(
        schema_version=data["schema_version"], status=data["status"], underlying=data["underlying"],
        session_date=date.fromisoformat(data["session_date"]), expiry=date.fromisoformat(data["expiry"]),
        wings=data["wings"], strike_interval=data["strike_interval"], row_count=data["row_count"],
        rows=tuple(rows), issues=tuple(data.get("issues", [])), provenance=data.get("provenance", PROVENANCE),
    )


def write_combined_csv(sessions: Sequence[HistoricalPositioningSession], output: str | Path) -> int:
    rows = [row for session in sessions if session.status == "AVAILABLE" for row in session.rows]
    path = Path(output)
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("", encoding="utf-8")
        return 0
    fieldnames = list(asdict(rows[0]).keys())
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            raw = _jsonable(asdict(row))
            writer.writerow(raw)
    return len(rows)


def write_combined_json(sessions: Sequence[HistoricalPositioningSession], output: str | Path) -> None:
    payload = {
        "schema_version": SCHEMA_VERSION,
        "provenance": PROVENANCE,
        "session_count": len(sessions),
        "available_session_count": sum(s.status == "AVAILABLE" for s in sessions),
        "row_count": sum(s.row_count for s in sessions if s.status == "AVAILABLE"),
        "sessions": [session_to_dict(s) for s in sessions],
    }
    path = Path(output)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def _main() -> None:
    from dotenv import load_dotenv
    from .gateways import GatewayError, UpstoxGateway
    from .historical_batch import load_historical_batch_manifest

    parser = argparse.ArgumentParser(description="Build historical per-strike positioning sidecar")
    parser.add_argument("--underlying", default="NSE_INDEX|Nifty 50")
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--wings", type=int, default=5)
    parser.add_argument("--cache-dir", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--csv-output", required=True)
    parser.add_argument("--refresh", action="store_true")
    parser.add_argument("--price-threshold-pct", type=float, default=0.0)
    parser.add_argument("--oi-threshold-pct", type=float, default=0.0)
    args = parser.parse_args()

    load_dotenv(Path(__file__).resolve().parents[2] / ".env")
    manifest = load_historical_batch_manifest(args.manifest)
    config = PositioningConfig(args.price_threshold_pct, args.oi_threshold_pct)
    gateway = None
    sessions: list[HistoricalPositioningSession] = []
    hits = misses = fetches = writes = 0
    try:
        for spec in sorted(manifest.sessions, key=lambda item: item.session_date):
            cached = None if args.refresh else load_session_cache(args.cache_dir, args.underlying, spec.session_date, spec.expiry, args.wings)
            if cached is not None:
                hits += 1
                sessions.append(cached)
                continue
            misses += 1
            try:
                if gateway is None:
                    gateway = UpstoxGateway(os.getenv("UPSTOX_ACCESS_TOKEN", ""))
                fetches += 1
                session = reconstruct_positioning_session(gateway, args.underlying, spec.session_date, spec.expiry, args.wings, config=config)
                sessions.append(session)
                if session.status == "AVAILABLE":
                    store_session_cache(args.cache_dir, session)
                    writes += 1
            except (GatewayError, OSError, ValueError) as error:
                sessions.append(HistoricalPositioningSession(SCHEMA_VERSION, "UNAVAILABLE", args.underlying, spec.session_date, spec.expiry, args.wings, 50, 0, (), (str(error),)))
    finally:
        if gateway is not None:
            gateway.close()

    write_combined_json(sessions, args.output)
    row_count = write_combined_csv(sessions, args.csv_output)
    available = sum(s.status == "AVAILABLE" for s in sessions)
    summary = {
        "status": "AVAILABLE" if available == len(sessions) else "PARTIAL",
        "requested_session_count": len(sessions),
        "available_session_count": available,
        "unavailable_session_count": len(sessions) - available,
        "row_count": row_count,
        "cache_hits": hits, "cache_misses": misses, "provider_fetches": fetches, "cache_writes": writes,
        "cache_dir": args.cache_dir, "output": args.output, "csv_output": args.csv_output,
        "provenance": PROVENANCE,
    }
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    _main()
