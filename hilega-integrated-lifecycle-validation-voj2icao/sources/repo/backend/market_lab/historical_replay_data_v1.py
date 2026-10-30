from __future__ import annotations

import argparse
import hashlib
import json
import os
from dataclasses import asdict, dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .domain import IST, Snapshot
from .gateways import UpstoxGateway
from .storage import Observation, make_engine

MODEL = "HISTORICAL_REPLAY_DATA_READINESS_V1"


@dataclass(frozen=True)
class DatasetStatus:
    name: str
    status: str
    required_for: str
    detail: str
    records: int | None = None
    path: str | None = None


def replay_cache_dir(session_date: date, root: str | Path = "data/live-observation/replay-cache") -> Path:
    return Path(root) / session_date.isoformat()


def _safe_name(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:16]


def futures_cache_path(session_date: date, root: str | Path = "data/live-observation/replay-cache") -> Path:
    return replay_cache_dir(session_date, root) / "futures-1m.json"


def option_cache_path(
    session_date: date,
    instrument_key: str,
    root: str | Path = "data/live-observation/replay-cache",
) -> Path:
    return replay_cache_dir(session_date, root) / "options-1m" / f"{_safe_name(instrument_key)}.json"


def _serialize_candles(candles: list[Any]) -> list[dict[str, Any]]:
    rows = []
    for candle in candles:
        if hasattr(candle, "model_dump"):
            row = candle.model_dump(mode="json")
        elif hasattr(candle, "__dataclass_fields__"):
            row = asdict(candle)
        else:
            row = dict(candle)
        for key, value in list(row.items()):
            if isinstance(value, (date, datetime)):
                row[key] = value.isoformat()
        rows.append(row)
    return rows


def snapshot_count(engine, session_date: date) -> int:
    with Session(engine) as session:
        return int(
            session.scalar(
                select(func.count())
                .select_from(Observation)
                .where(Observation.session_date == session_date.isoformat())
            )
            or 0
        )


def snapshot_span(engine, session_date: date) -> tuple[str | None, str | None]:
    with Session(engine) as session:
        rows = session.scalars(
            select(Observation)
            .where(Observation.session_date == session_date.isoformat())
            .order_by(Observation.id)
        ).all()
    if not rows:
        return None, None
    first = Snapshot.model_validate(rows[0].snapshot).received_at
    last = Snapshot.model_validate(rows[-1].snapshot).received_at
    return first.isoformat(), last.isoformat()


def readiness(
    session_date: date,
    *,
    engine=None,
    cache_root: str | Path = "data/live-observation/replay-cache",
) -> dict[str, Any]:
    engine = engine or make_engine()
    count = snapshot_count(engine, session_date)
    first, last = snapshot_span(engine, session_date)

    fpath = futures_cache_path(session_date, cache_root)
    futures_rows = 0
    if fpath.exists():
        try:
            futures_rows = len(json.loads(fpath.read_text()).get("candles", []))
        except Exception:
            futures_rows = 0

    datasets = [
        DatasetStatus(
            name="OPTION_CHAIN_SNAPSHOTS",
            status="AVAILABLE" if count > 0 else "MISSING",
            required_for="CHECKPOINT_ANALYSIS",
            detail=(
                f"{count} stored production snapshots"
                if count > 0
                else "No stored option-chain snapshots for this session"
            ),
            records=count,
        ),
        DatasetStatus(
            name="NIFTY_FUTURES_1M",
            status="AVAILABLE" if futures_rows > 0 else "MISSING",
            required_for="C2_FUTURES_CONFIRMATION",
            detail=(
                f"{futures_rows} cached historical futures candles"
                if futures_rows > 0
                else "Historical futures candles have not been cached"
            ),
            records=futures_rows or None,
            path=str(fpath),
        ),
        DatasetStatus(
            name="EXACT_OPTION_1M",
            status="ON_DEMAND",
            required_for="TRADE_LIFECYCLE",
            detail=(
                "Exact option candles are checked/downloaded only for instruments "
                "actually selected by the causal replay. No nearest-strike fallback."
            ),
            path=str(replay_cache_dir(session_date, cache_root) / "options-1m"),
        ),
    ]

    return {
        "model": MODEL,
        "session_date": session_date.isoformat(),
        "snapshot_first_received_at": first,
        "snapshot_last_received_at": last,
        "checkpoint_analysis_ready": count > 0,
        "full_replay_prerequisites_ready": count > 0 and futures_rows > 0,
        "exact_option_data": "ON_DEMAND",
        "datasets": [asdict(item) for item in datasets],
        "execution_enabled": False,
        "paper_order_enabled": False,
        "observation_only": True,
    }


def download_futures(
    session_date: date,
    *,
    cache_root: str | Path = "data/live-observation/replay-cache",
) -> dict[str, Any]:
    from .midpoint_v2_nifty_futures_vwap_v1 import (
        _client,
        available_expiries,
        fetch_one_minute_candles,
        resolve_active_future,
    )

    client = _client()
    expiries = available_expiries(client)
    contract = resolve_active_future(client, session_date, expiries)
    raw = fetch_one_minute_candles(client, contract, session_date)

    # Current-session futures can legitimately return zero rows from the
    # standard historical endpoint before the provider has finalized EOD data.
    # For today's still-current contract, fall back to the causal intraday API.
    if (
        not raw
        and contract.source == "CURRENT_INSTRUMENT_SEARCH_API"
        and session_date == datetime.now(IST).date()
    ):
        from urllib.parse import quote
        from .midpoint_v2_nifty_futures_vwap_v1 import normalize_candles

        encoded = quote(contract.instrument_key, safe="")
        response = client.get(
            f"/v3/historical-candle/intraday/{encoded}/minutes/1"
        )
        response.raise_for_status()

        intraday_raw = (
            response.json()
            .get("data", {})
            .get("candles", [])
        )
        raw = normalize_candles(intraday_raw)

    if not raw:
        raise RuntimeError(
            "No 1-minute NIFTY futures candles returned for "
            f"{session_date} {contract.instrument_key} "
            f"using {contract.source}"
        )

    path = futures_cache_path(session_date, cache_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "model": MODEL,
        "session_date": session_date.isoformat(),
        "instrument_key": contract.instrument_key,
        "expiry": contract.expiry.isoformat(),
        "trading_symbol": contract.trading_symbol,
        "contract_source": contract.source,
        "candles": raw,
    }
    path.write_text(json.dumps(payload, indent=2, default=str))
    return {
        "status": "DOWNLOADED",
        "dataset": "NIFTY_FUTURES_1M",
        "session_date": session_date.isoformat(),
        "records": len(raw),
        "path": str(path),
        "instrument_key": contract.instrument_key,
        "contract_source": contract.source,
    }


def download_exact_option(
    session_date: date,
    instrument_key: str,
    *,
    cache_root: str | Path = "data/live-observation/replay-cache",
) -> dict[str, Any]:
    load_dotenv(".env")
    gateway = UpstoxGateway(os.getenv("UPSTOX_ACCESS_TOKEN", ""))
    candles = gateway.historical_option_candles(instrument_key, session_date)

    path = option_cache_path(session_date, instrument_key, cache_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "model": MODEL,
        "session_date": session_date.isoformat(),
        "instrument_key": instrument_key,
        "candles": _serialize_candles(candles),
    }
    path.write_text(json.dumps(payload, indent=2, default=str))
    return {
        "status": "DOWNLOADED",
        "dataset": "EXACT_OPTION_1M",
        "session_date": session_date.isoformat(),
        "instrument_key": instrument_key,
        "records": len(candles),
        "path": str(path),
    }


def download_missing(
    session_date: date,
    *,
    cache_root: str | Path = "data/live-observation/replay-cache",
) -> dict[str, Any]:
    before = readiness(session_date, cache_root=cache_root)
    actions = []

    futures = next(item for item in before["datasets"] if item["name"] == "NIFTY_FUTURES_1M")
    if futures["status"] == "MISSING":
        actions.append(download_futures(session_date, cache_root=cache_root))

    return {
        "model": MODEL,
        "session_date": session_date.isoformat(),
        "actions": actions,
        "readiness": readiness(session_date, cache_root=cache_root),
        "note": (
            "Exact option 1m candles remain ON_DEMAND until the replay selects "
            "an exact CE/PE instrument."
        ),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", required=True)
    parser.add_argument("--cache-root", default="data/live-observation/replay-cache")
    parser.add_argument("action", choices=("check", "download-missing", "download-option"))
    parser.add_argument("--instrument-key")
    args = parser.parse_args()

    session_date = date.fromisoformat(args.date)

    if args.action == "check":
        result = readiness(session_date, cache_root=args.cache_root)
    elif args.action == "download-missing":
        result = download_missing(session_date, cache_root=args.cache_root)
    else:
        if not args.instrument_key:
            raise SystemExit("--instrument-key is required for download-option")
        result = download_exact_option(
            session_date,
            args.instrument_key,
            cache_root=args.cache_root,
        )

    print(json.dumps(result, indent=2, default=str))


if __name__ == "__main__":
    main()
