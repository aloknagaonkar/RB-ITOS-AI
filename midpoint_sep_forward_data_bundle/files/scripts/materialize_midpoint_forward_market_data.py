#!/usr/bin/env python3
"""Materialize exact September 9-29 NIFTY/futures forward-OOS minutes.

The frozen 480-session historical evidence is never modified. Existing exact
UI-replay minute files are reused when available; missing dates are acquired
from Upstox. Every published session must contain the exact 360 paired minutes
from 09:15 through 15:14 IST with positive futures volume and causal cumulative
futures VWAP.
"""

from __future__ import annotations

import argparse
import json
import os
import tempfile
from datetime import date, datetime, time, timedelta
from pathlib import Path

from dotenv import load_dotenv

from market_lab.domain import IST
from market_lab.midpoint_v2_nifty_futures_vwap_v1 import (
    FutureContract,
    _client,
    available_expiries,
    fetch_one_minute_candles,
    resolve_active_future,
)
from market_lab.upstox_live_shadow_sources_v1 import UpstoxLiveShadowSourcesV1


DEFAULT_DATES = tuple(
    date(2026, 9, day)
    for day in (9, 10, 11, 15, 16, 17, 18, 21, 22, 23, 24, 25, 28, 29)
)
ROOT = Path(
    "data/historical-evidence/hilega-pcr-oi-support-research-v1/"
    "midpoint-forward-oos-2026-09-09-to-29-v2"
)
REPLAY_ROOT = Path(
    "data/historical-evidence/hilega-pcr-oi-support-research-v1/"
    "midpoint-ui-replay-v1"
)
INDEX = "NSE_INDEX|Nifty 50"
START = time(9, 15)
END = time(15, 14)
SEPTEMBER_FUTURE = FutureContract(
    instrument_key="NSE_FO|68407",
    expiry=date(2026, 9, 29),
    trading_symbol="NIFTY SEP 2026 FUT",
    instrument_type="FUT",
    # On the first day after expiry Upstox can return HTTP 400 from the
    # expired-instrument candle route even though the standard V3 historical
    # route still serves the pinned instrument key. Keep the contract pinned;
    # select only the working historical transport.
    source="CURRENT_INSTRUMENT_SEARCH_API",
)


def minute(value) -> datetime:
    timestamp = (
        value
        if isinstance(value, datetime)
        else datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    )
    if timestamp.tzinfo is None:
        raise ValueError("AWARE_TIMESTAMP_REQUIRED")
    timestamp = timestamp.astimezone(IST)
    if timestamp.second or timestamp.microsecond:
        raise ValueError(f"EXACT_MINUTE_REQUIRED_{timestamp.isoformat()}")
    return timestamp


def expected_minutes(day: date) -> list[datetime]:
    first = datetime.combine(day, START, IST)
    return [first + timedelta(minutes=offset) for offset in range(360)]


def normalize_index(rows, day: date) -> dict[datetime, dict]:
    output = {}
    for candle in rows:
        timestamp = minute(candle.timestamp)
        if timestamp.date() != day or not START <= timestamp.time() <= END:
            continue
        if timestamp in output:
            raise ValueError(f"DUPLICATE_INDEX_MINUTE_{timestamp.isoformat()}")
        output[timestamp] = {
            "open": float(candle.open),
            "high": float(candle.high),
            "low": float(candle.low),
            "close": float(candle.close),
        }
    return output


def normalize_futures(rows, day: date) -> dict[datetime, dict]:
    output = {}
    for candle in rows:
        timestamp = minute(candle["timestamp"])
        if timestamp.date() != day or not START <= timestamp.time() <= END:
            continue
        if timestamp in output:
            raise ValueError(f"DUPLICATE_FUTURES_MINUTE_{timestamp.isoformat()}")
        volume = float(candle.get("volume") or 0.0)
        if volume <= 0:
            raise ValueError(f"FUTURES_VOLUME_MISSING_{timestamp.isoformat()}")
        output[timestamp] = {
            "close": float(candle["close"]),
            "volume": volume,
        }
    price_volume = 0.0
    cumulative_volume = 0.0
    for timestamp in sorted(output):
        row = output[timestamp]
        price_volume += row["close"] * row["volume"]
        cumulative_volume += row["volume"]
        row["vwap"] = price_volume / cumulative_volume
    return output


def validate_and_join(
    day: date, index: dict[datetime, dict], futures: dict[datetime, dict]
) -> list[dict]:
    expected = expected_minutes(day)
    if set(index) != set(expected) or set(futures) != set(expected):
        missing_index = [x.strftime("%H:%M") for x in expected if x not in index]
        missing_futures = [x.strftime("%H:%M") for x in expected if x not in futures]
        raise ValueError(
            f"EXACT_360_PAIR_REQUIRED {day} "
            f"index_missing={missing_index[:10]} futures_missing={missing_futures[:10]}"
        )
    return [
        {
            "session_date": day.isoformat(),
            "timestamp": timestamp.isoformat(),
            "underlying_open": index[timestamp]["open"],
            "underlying_high": index[timestamp]["high"],
            "underlying_low": index[timestamp]["low"],
            "underlying_close": index[timestamp]["close"],
            "futures_close": futures[timestamp]["close"],
            "futures_volume": futures[timestamp]["volume"],
            "futures_vwap": futures[timestamp]["vwap"],
            "data_status": "BOTH",
        }
        for timestamp in expected
    ]


def load_replay(day: date) -> list[dict] | None:
    path = REPLAY_ROOT / day.isoformat() / "minutes.jsonl"
    if not path.exists():
        return None
    metadata_path = path.parent / "metadata.json"
    if metadata_path.exists():
        metadata = json.loads(metadata_path.read_text())
        observed_key = metadata.get("futures_instrument_key")
        observed_expiry = metadata.get("futures_expiry")
        if observed_key not in (None, SEPTEMBER_FUTURE.instrument_key):
            raise ValueError(
                f"REPLAY_FRONT_FUTURE_KEY_MISMATCH_{day}_{observed_key}"
            )
        if observed_expiry not in (None, SEPTEMBER_FUTURE.expiry.isoformat()):
            raise ValueError(
                f"REPLAY_FRONT_FUTURE_EXPIRY_MISMATCH_{day}_{observed_expiry}"
            )
    source = [json.loads(line) for line in path.read_text().splitlines() if line]
    if len(source) != 360:
        raise ValueError(f"REPLAY_NOT_EXACT_360_{day}_{len(source)}")
    output = []
    for row in source:
        required = {
            "timestamp", "underlying_open", "underlying_high", "underlying_low",
            "underlying_close", "futures_close", "futures_vwap",
        }
        if not required.issubset(row):
            raise ValueError(f"REPLAY_FIELDS_MISSING_{day}")
        volume = row.get("futures_volume")
        if volume is None:
            # UI replay historically omitted volume after VWAP was materialized.
            volume = 1.0
        output.append({
            "session_date": day.isoformat(),
            "timestamp": minute(row["timestamp"]).isoformat(),
            "underlying_open": float(row["underlying_open"]),
            "underlying_high": float(row["underlying_high"]),
            "underlying_low": float(row["underlying_low"]),
            "underlying_close": float(row["underlying_close"]),
            "futures_close": float(row["futures_close"]),
            "futures_volume": float(volume),
            "futures_vwap": float(row["futures_vwap"]),
            "data_status": "BOTH",
        })
    if [minute(row["timestamp"]) for row in output] != expected_minutes(day):
        raise ValueError(f"REPLAY_MINUTE_SEQUENCE_INVALID_{day}")
    return output


def write_jsonl(path: Path, rows: list[dict]) -> None:
    with path.open("w") as handle:
        for row in rows:
            handle.write(json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dates", nargs="+", type=date.fromisoformat, default=DEFAULT_DATES)
    parser.add_argument("--output-root", type=Path, default=ROOT)
    parser.add_argument(
        "--broker-only", action="store_true",
        help="ignore existing UI replay files and reacquire every session",
    )
    arguments = parser.parse_args()
    days = sorted(set(arguments.dates))
    if not days:
        raise SystemExit("STOP: no dates requested")
    if any(day > datetime.now(IST).date() for day in days):
        raise SystemExit("STOP: future session requested")
    if arguments.output_root.exists():
        raise SystemExit(
            f"STOP: output already exists: {arguments.output_root}. "
            "Existing forward evidence is immutable; use a new --output-root."
        )

    staged: list[tuple[date, list[dict], dict]] = []
    missing = []
    if not arguments.broker_only:
        for day in days:
            rows = load_replay(day)
            if rows is None:
                missing.append(day)
            else:
                staged.append((day, rows, {
                    "source": "EXISTING_EXACT_UI_REPLAY",
                    "futures_instrument_key": SEPTEMBER_FUTURE.instrument_key,
                    "futures_expiry": SEPTEMBER_FUTURE.expiry.isoformat(),
                }))
                print("VALIDATED REPLAY", day, "minutes", len(rows))
    else:
        missing = list(days)

    if missing:
        load_dotenv(".env")
        token = os.getenv("UPSTOX_ACCESS_TOKEN")
        if not token:
            raise SystemExit("STOP: UPSTOX_ACCESS_TOKEN missing for absent dates")
        sources = UpstoxLiveShadowSourcesV1(token)
        try:
            with _client() as client:
                expiries = available_expiries(client)
                for day in missing:
                    index_rows = sources.historical_candles(INDEX, day)
                    contract = (
                        SEPTEMBER_FUTURE
                        if date(2026, 9, 9) <= day <= date(2026, 9, 29)
                        else resolve_active_future(client, day, expiries)
                    )
                    if day <= date(2026, 9, 29) and (
                        contract.instrument_key != SEPTEMBER_FUTURE.instrument_key
                        or contract.expiry != SEPTEMBER_FUTURE.expiry
                    ):
                        raise AssertionError(
                            f"FRONT_FUTURE_CONTRACT_MISMATCH_{day}_{contract}"
                        )
                    futures_rows = fetch_one_minute_candles(client, contract, day)
                    rows = validate_and_join(
                        day,
                        normalize_index(index_rows, day),
                        normalize_futures(futures_rows, day),
                    )
                    metadata = {
                        "source": "UPSTOX_HISTORICAL_EXACT_1M",
                        "futures_instrument_key": contract.instrument_key,
                        "futures_expiry": contract.expiry.isoformat(),
                    }
                    staged.append((day, rows, metadata))
                    print(
                        "VALIDATED BROKER", day, "minutes", len(rows),
                        "futures", contract.instrument_key,
                        "expiry", contract.expiry,
                    )
        finally:
            sources.close()

    staged.sort(key=lambda item: item[0])
    actual = [day for day, _, _ in staged]
    if actual != days:
        raise AssertionError(f"staged dates differ requested={days} actual={actual}")

    arguments.output_root.mkdir(parents=True, exist_ok=False)
    manifest_rows = []
    for day, rows, metadata in staged:
        folder = arguments.output_root / day.isoformat()
        folder.mkdir()
        write_jsonl(folder / "minutes.jsonl", rows)
        session_metadata = {
            "session_date": day.isoformat(),
            "block": "FORWARD_OOS_2026-09",
            "minute_count": len(rows),
            "first_minute": rows[0]["timestamp"],
            "last_minute": rows[-1]["timestamp"],
            **metadata,
            "observation_only": True,
            "execution_enabled": False,
            "paper_order_enabled": False,
            "quantity": None,
        }
        (folder / "metadata.json").write_text(
            json.dumps(session_metadata, indent=2, sort_keys=True) + "\n"
        )
        manifest_rows.append(session_metadata)
    manifest = {
        "model": "MIDPOINT_FORWARD_OOS_MARKET_DATA_V2",
        "session_count": len(manifest_rows),
        "sessions": manifest_rows,
        "frozen_480_modified": False,
        "contract_guard": {
            "2026-09-09_to_2026-09-29": {
                "instrument_key": SEPTEMBER_FUTURE.instrument_key,
                "expiry": SEPTEMBER_FUTURE.expiry.isoformat(),
            }
        },
        "observation_only": True,
    }
    with tempfile.NamedTemporaryFile(
        mode="w", dir=arguments.output_root, prefix="manifest.", suffix=".tmp", delete=False
    ) as handle:
        json.dump(manifest, handle, indent=2, sort_keys=True)
        temporary = Path(handle.name)
    temporary.replace(arguments.output_root / "manifest.json")
    print(
        "PUBLISHED", len(manifest_rows), "forward OOS sessions to",
        arguments.output_root,
    )
    print("Frozen 480-session evidence, live audits, services and orders untouched.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
