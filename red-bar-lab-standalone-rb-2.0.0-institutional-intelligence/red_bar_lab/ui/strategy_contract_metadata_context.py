from __future__ import annotations

from pathlib import Path
from typing import Mapping

import pandas as pd


METADATA_CONTEXT_VERSION = "CONTRACT-METADATA-CONTEXT-V1"


def _timestamp(value: object) -> pd.Timestamp | None:
    if value in (None, "", "Unavailable"):
        return None
    try:
        result = pd.Timestamp(value)
    except (TypeError, ValueError):
        return None
    if pd.isna(result):
        return None
    if result.tzinfo is None:
        return result.tz_localize("Asia/Kolkata")
    return result.tz_convert("Asia/Kolkata")


def _number(value: object) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return None if pd.isna(result) else result


def _load(path_value: object) -> pd.DataFrame:
    if not path_value:
        return pd.DataFrame()
    try:
        path = Path(str(path_value))
        if not path.exists() or not path.is_file():
            return pd.DataFrame()
        return pd.read_json(path) if path.suffix.lower() == ".json" else pd.read_csv(path)
    except Exception:
        return pd.DataFrame()


def _first(row: Mapping[str, object], *names: str) -> object:
    for name in names:
        value = row.get(name)
        if value not in (None, "", "Unavailable"):
            return value
    return None


def _exact_snapshot(database, instrument_key: str, snapshot_ts: pd.Timestamp) -> dict[str, object] | None:
    source = getattr(database, "_database", database)
    try:
        rows = source.read_option_chain_history(
            instrument_key,
            snapshot_ts.date().isoformat(),
            snapshot_ts.date().isoformat(),
            limit=2000,
        ) or []
    except Exception:
        return None
    for raw in rows:
        row = dict(raw)
        if str(row.get("collector_mode") or "").upper() != "ONLINE":
            continue
        if _timestamp(row.get("snapshot_timestamp")) == snapshot_ts:
            return row
    return None


def _artifact_row(chain: pd.DataFrame, side: str, strike: float | None) -> dict[str, object]:
    if chain.empty or strike is None:
        return {}
    strike_column = "strike" if "strike" in chain.columns else "strike_price" if "strike_price" in chain.columns else None
    if not strike_column:
        return {}
    values = pd.to_numeric(chain[strike_column], errors="coerce")
    matches = chain.loc[(values - float(strike)).abs() < 1e-9]
    if matches.empty:
        return {}
    return dict(matches.iloc[-1].to_dict())


def enrich_contract_execution_metadata(
    readiness: Mapping[str, object],
    *,
    database,
    instrument_key: str,
    artifact_loader=_load,
) -> dict[str, object]:
    """Restore execution metadata from the exact selected snapshot artifact."""
    result = dict(readiness)
    snapshot_ts = _timestamp(result.get("snapshot_timestamp"))
    rows = [dict(row) for row in result.get("contract_rows") or []]
    if snapshot_ts is None or database is None:
        return {
            **result,
            "contract_rows": rows,
            "metadata_context_status": "UNAVAILABLE",
            "metadata_context_reason": "Exact snapshot or database is unavailable.",
            "metadata_context_version": METADATA_CONTEXT_VERSION,
            "metadata_context_read_only": True,
        }

    snapshot = _exact_snapshot(database, instrument_key, snapshot_ts)
    if snapshot is None:
        return {
            **result,
            "contract_rows": rows,
            "metadata_context_status": "UNAVAILABLE",
            "metadata_context_reason": "Exact selected snapshot could not be reopened.",
            "metadata_context_version": METADATA_CONTEXT_VERSION,
            "metadata_context_read_only": True,
        }

    chain = artifact_loader(snapshot.get("chain_artifact_path"))
    if chain.empty:
        return {
            **result,
            "contract_rows": rows,
            "metadata_context_status": "UNAVAILABLE",
            "metadata_context_reason": "Exact snapshot artifact is unreadable.",
            "metadata_context_version": METADATA_CONTEXT_VERSION,
            "metadata_context_read_only": True,
        }

    enriched: list[dict[str, object]] = []
    complete = 0
    for raw in rows:
        row = dict(raw)
        side = str(row.get("option_side") or "").upper()
        prefix = "call" if side == "CE" else "put" if side == "PE" else ""
        artifact = _artifact_row(chain, side, _number(row.get("strike")))
        sources: dict[str, str] = {}

        aliases = {
            "instrument_token": (
                f"{prefix}_instrument_token", f"{prefix}_token", f"{prefix}_security_id"
            ),
            "instrument_key": (
                f"{prefix}_instrument_key", f"{prefix}_instrument_token", f"{prefix}_security_id"
            ),
            "trading_symbol": (
                f"{prefix}_tradingsymbol", f"{prefix}_trading_symbol", f"{prefix}_symbol"
            ),
            "exchange": (
                f"{prefix}_exchange", f"{prefix}_exchange_segment", "exchange", "exchange_segment"
            ),
            "lot_size": (
                f"{prefix}_lot_size", f"{prefix}_contract_lot_size", "lot_size", "contract_lot_size"
            ),
            "tick_size": (
                f"{prefix}_tick_size", "tick_size"
            ),
            "expiry": (
                f"{prefix}_expiry", "expiry", "option_expiry"
            ),
        }
        for field, names in aliases.items():
            existing = row.get(field)
            if existing not in (None, "", "Unavailable"):
                sources[field] = "SECTION_5A_NORMALIZED"
                continue
            value = _first(artifact, *names)
            if value not in (None, "", "Unavailable"):
                row[field] = value
                sources[field] = "EXACT_CHAIN_ARTIFACT"
            else:
                sources[field] = "UNAVAILABLE"

        required = (
            row.get("instrument_token") not in (None, "", "Unavailable"),
            row.get("trading_symbol") not in (None, "", "Unavailable"),
            row.get("exchange") not in (None, "", "Unavailable"),
            (_number(row.get("lot_size")) or 0) > 0,
            (_number(row.get("tick_size")) or 0) > 0,
        )
        row["execution_metadata_complete"] = all(required)
        row["execution_metadata_sources"] = sources
        row["metadata_context_version"] = METADATA_CONTEXT_VERSION
        row["metadata_context_read_only"] = True
        complete += int(all(required))
        enriched.append(row)

    status = "READY" if rows and complete == len(rows) else "PARTIAL" if complete else "UNAVAILABLE"
    return {
        **result,
        "contract_rows": enriched,
        "metadata_context_status": status,
        "metadata_context_reason": f"{complete} of {len(rows)} contract rows have complete execution metadata.",
        "metadata_complete_count": complete,
        "metadata_context_version": METADATA_CONTEXT_VERSION,
        "metadata_context_read_only": True,
    }
