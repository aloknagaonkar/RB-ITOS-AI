from __future__ import annotations

from dataclasses import asdict
from datetime import date, datetime
from hashlib import sha256
import json
import os
from pathlib import Path
from uuid import uuid4

from red_bar_lab.domain.red_bar_v2 import OptionSide

from .paper_market_data_readiness_models import (
    ContractReadinessEvidence,
    ContractReadinessStatus,
    MarketDataReadinessReport,
    MarketDataReadinessStatus,
    SCHEMA_VERSION,
)


class ReadinessStateError(Exception): pass
class ReadinessStateCorruptionError(ReadinessStateError): pass
class ReadinessStateUnavailableError(ReadinessStateError): pass
class ReadinessStatePersistenceError(ReadinessStateError): pass


def _payload(report: MarketDataReadinessReport) -> dict[str, object]:
    def iso(value): return value.isoformat() if value is not None else None
    return {
        "probe_id": report.probe_id,
        "provider": report.provider,
        "underlying": report.underlying,
        "underlying_instrument_key": report.underlying_instrument_key,
        "evaluated_at": iso(report.evaluated_at),
        "spot_price": report.spot_price,
        "spot_timestamp": iso(report.spot_timestamp),
        "expiry": iso(report.expiry),
        "strike_interval": report.strike_interval,
        "atm_strike": report.atm_strike,
        "expected_contract_count": report.expected_contract_count,
        "observed_contract_count": report.observed_contract_count,
        "ready_contract_count": report.ready_contract_count,
        "ce_coverage": report.ce_coverage,
        "pe_coverage": report.pe_coverage,
        "status": report.status.value,
        "reason_code": report.reason_code,
        "contracts": [
            {
                "instrument_key": row.instrument_key,
                "trading_symbol": row.trading_symbol,
                "option_side": row.option_side.value,
                "strike": row.strike,
                "expiry": row.expiry.isoformat(),
                "moneyness": row.moneyness,
                "distance_steps": row.distance_steps,
                "lot_size": row.lot_size,
                "last_price": row.last_price,
                "bid_price": row.bid_price,
                "ask_price": row.ask_price,
                "spread_percentage": row.spread_percentage,
                "quote_timestamp": iso(row.quote_timestamp),
                "status": row.status.value,
                "reason_code": row.reason_code,
            }
            for row in report.contracts
        ],
        "schema_version": report.schema_version,
    }


def _canonical(value: dict[str, object]) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False).encode("utf-8")


def _parse_datetime(value: object | None) -> datetime | None:
    if value is None: return None
    if type(value) is not str: raise ReadinessStateCorruptionError("datetime type invalid")
    try: result = datetime.fromisoformat(value)
    except ValueError as exc: raise ReadinessStateCorruptionError("datetime invalid") from exc
    if result.tzinfo is None or result.utcoffset() is None: raise ReadinessStateCorruptionError("datetime naive")
    return result


def _parse_date(value: object | None) -> date | None:
    if value is None: return None
    if type(value) is not str: raise ReadinessStateCorruptionError("date type invalid")
    try: return date.fromisoformat(value)
    except ValueError as exc: raise ReadinessStateCorruptionError("date invalid") from exc


def deserialize_report(payload: object) -> MarketDataReadinessReport:
    if not isinstance(payload, dict): raise ReadinessStateCorruptionError("payload invalid")
    try:
        raw_contracts = payload["contracts"]
        if not isinstance(raw_contracts, list) or len(raw_contracts) > 18: raise ReadinessStateCorruptionError("contracts invalid")
        contracts = tuple(
            ContractReadinessEvidence(
                instrument_key=row["instrument_key"], trading_symbol=row["trading_symbol"], option_side=OptionSide(row["option_side"]), strike=row["strike"], expiry=_parse_date(row["expiry"]), moneyness=row["moneyness"], distance_steps=row["distance_steps"], lot_size=row["lot_size"], last_price=row["last_price"], bid_price=row["bid_price"], ask_price=row["ask_price"], spread_percentage=row["spread_percentage"], quote_timestamp=_parse_datetime(row["quote_timestamp"]), status=ContractReadinessStatus(row["status"]), reason_code=row["reason_code"]
            ) for row in raw_contracts
        )
        return MarketDataReadinessReport(
            probe_id=payload["probe_id"], provider=payload["provider"], underlying=payload["underlying"], underlying_instrument_key=payload["underlying_instrument_key"], evaluated_at=_parse_datetime(payload["evaluated_at"]), spot_price=payload["spot_price"], spot_timestamp=_parse_datetime(payload["spot_timestamp"]), expiry=_parse_date(payload["expiry"]), strike_interval=payload["strike_interval"], atm_strike=payload["atm_strike"], expected_contract_count=payload["expected_contract_count"], observed_contract_count=payload["observed_contract_count"], ready_contract_count=payload["ready_contract_count"], ce_coverage=payload["ce_coverage"], pe_coverage=payload["pe_coverage"], status=MarketDataReadinessStatus(payload["status"]), reason_code=payload["reason_code"], contracts=contracts, schema_version=payload["schema_version"]
        )
    except ReadinessStateCorruptionError: raise
    except (KeyError, TypeError, ValueError) as exc: raise ReadinessStateCorruptionError("readiness payload corrupt") from exc


class AtomicJsonMarketDataReadinessStore:
    def __init__(self, path: Path) -> None: self.path = Path(path)

    def save(self, report: MarketDataReadinessReport) -> None:
        payload = _payload(report); digest = sha256(_canonical(payload)).hexdigest()
        envelope = {"schema_version": SCHEMA_VERSION, "payload": payload, "payload_sha256": digest}
        data = _canonical(envelope)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_name(f".{self.path.name}.{uuid4().hex}.tmp")
        try:
            with temporary.open("wb") as handle:
                handle.write(data); handle.flush(); os.fsync(handle.fileno())
            os.replace(temporary, self.path)
        except OSError as exc:
            try: temporary.unlink(missing_ok=True)
            except OSError: pass
            raise ReadinessStatePersistenceError("readiness state persistence failed") from exc

    def load(self) -> MarketDataReadinessReport | None:
        if not self.path.exists(): return None
        try: envelope = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc: raise ReadinessStateUnavailableError("readiness state unavailable") from exc
        if not isinstance(envelope, dict) or envelope.get("schema_version") != SCHEMA_VERSION: raise ReadinessStateCorruptionError("readiness envelope invalid")
        payload = envelope.get("payload"); supplied = envelope.get("payload_sha256")
        if type(supplied) is not str or not isinstance(payload, dict) or sha256(_canonical(payload)).hexdigest() != supplied: raise ReadinessStateCorruptionError("readiness digest mismatch")
        return deserialize_report(payload)
