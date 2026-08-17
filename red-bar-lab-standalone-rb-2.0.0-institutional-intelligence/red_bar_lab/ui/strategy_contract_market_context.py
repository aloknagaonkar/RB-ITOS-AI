from __future__ import annotations

from pathlib import Path
from typing import Mapping

import pandas as pd


def _number(value: object) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    if pd.isna(result):
        return None
    return result


def _timestamp(value: object) -> pd.Timestamp | None:
    if value in (None, "", "Unavailable"):
        return None
    try:
        ts = pd.Timestamp(value)
    except (TypeError, ValueError):
        return None
    if pd.isna(ts):
        return None
    if ts.tzinfo is None:
        return ts.tz_localize("Asia/Kolkata")
    return ts.tz_convert("Asia/Kolkata")


def _load_artifact(path_value: object) -> pd.DataFrame:
    if not path_value:
        return pd.DataFrame()
    try:
        path = Path(str(path_value))
        if not path.exists() or not path.is_file():
            return pd.DataFrame()
        if path.suffix.lower() == ".json":
            return pd.read_json(path)
        return pd.read_csv(path)
    except Exception:
        return pd.DataFrame()


def _first_numeric(mapping: Mapping[str, object], names: tuple[str, ...]) -> tuple[float | None, str | None]:
    for name in names:
        value = _number(mapping.get(name))
        if value is not None and value > 0:
            return value, name
    return None, None


def _chain_numeric(chain: pd.DataFrame, names: tuple[str, ...]) -> tuple[float | None, str | None]:
    for name in names:
        if name not in chain.columns:
            continue
        values = pd.to_numeric(chain[name], errors="coerce").dropna()
        values = values[values > 0]
        if not values.empty:
            return float(values.iloc[-1]), name
    return None, None


def _nearest_atm(chain: pd.DataFrame, spot: float) -> tuple[float | None, str]:
    for column in ("strike", "strike_price"):
        if column not in chain.columns:
            continue
        strikes = sorted({float(value) for value in pd.to_numeric(chain[column], errors="coerce").dropna() if float(value) > 0})
        if strikes:
            return min(strikes, key=lambda strike: (abs(strike - spot), strike)), f"NEAREST_AVAILABLE_{column.upper()}"
    return None, "UNAVAILABLE_NO_STRIKES"


def enrich_contract_market_context(
    readiness: Mapping[str, object],
    *,
    database,
    instrument_key: str,
    artifact_loader=_load_artifact,
) -> dict[str, object]:
    """Attach spot and ATM from the exact Section 5A point-in-time snapshot.

    The selected snapshot timestamp is authoritative. No current quote, later snapshot,
    or cross-strategy context is consulted.
    """
    result = dict(readiness)
    base = {
        **result,
        "spot_price": result.get("spot_price"),
        "atm_strike": result.get("atm_strike"),
        "spot_source": str(result.get("spot_source") or "UNAVAILABLE"),
        "atm_source": str(result.get("atm_source") or "UNAVAILABLE"),
        "market_context_status": "UNAVAILABLE",
        "market_context_reason": "Section 5A snapshot context is unavailable.",
    }
    snapshot_ts = _timestamp(result.get("snapshot_timestamp"))
    bundle_ts = _timestamp(result.get("bundle_timestamp"))
    if snapshot_ts is None or bundle_ts is None or snapshot_ts > bundle_ts:
        return base

    source_database = getattr(database, "_database", database)
    rows = list(
        source_database.read_option_chain_history(
            instrument_key,
            snapshot_ts.date().isoformat(),
            snapshot_ts.date().isoformat(),
            limit=2000,
        )
        or []
    )
    exact: dict[str, object] | None = None
    for raw in rows:
        row = dict(raw)
        if str(row.get("collector_mode") or "").upper() != "ONLINE":
            continue
        row_ts = _timestamp(row.get("snapshot_timestamp"))
        if row_ts is not None and row_ts == snapshot_ts:
            exact = row
            break
    if exact is None:
        return {
            **base,
            "market_context_reason": "The exact Section 5A snapshot record could not be resolved.",
        }

    chain = artifact_loader(exact.get("chain_artifact_path"))
    spot, spot_field = _first_numeric(
        exact,
        (
            "spot_price",
            "underlying_spot",
            "underlying_price",
            "underlying_ltp",
            "spot",
            "underlying_value",
        ),
    )
    spot_source = f"SNAPSHOT_METADATA:{spot_field}" if spot_field else "UNAVAILABLE"
    if spot is None and not chain.empty:
        spot, spot_field = _chain_numeric(
            chain,
            (
                "spot_price",
                "underlying_spot",
                "underlying_price",
                "underlying_ltp",
                "spot",
                "underlying_value",
            ),
        )
        spot_source = f"CHAIN_ARTIFACT:{spot_field}" if spot_field else "UNAVAILABLE"

    atm, atm_field = _first_numeric(exact, ("atm_strike", "atm", "at_the_money_strike"))
    atm_source = f"SNAPSHOT_METADATA:{atm_field}" if atm_field else "UNAVAILABLE"
    if atm is None and spot is not None and not chain.empty:
        atm, atm_source = _nearest_atm(chain, spot)

    if spot is None:
        status = "UNAVAILABLE"
        reason = "Point-in-time underlying spot is absent from the selected snapshot and artifact."
    elif atm is None:
        status = "PARTIAL"
        reason = "Point-in-time spot is available, but ATM cannot be resolved from snapshot strikes."
    else:
        status = "READY"
        reason = "Spot and ATM are aligned to the exact Section 5A snapshot timestamp."

    return {
        **base,
        "spot_price": spot,
        "atm_strike": atm,
        "spot_source": spot_source,
        "atm_source": atm_source,
        "market_context_status": status,
        "market_context_reason": reason,
    }
