from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime
import hashlib
import json
from pathlib import Path
import sqlite3
from typing import Iterable

import pandas as pd

from red_bar_lab.utils import safe_float


EVIDENCE_SCHEMA = """
CREATE TABLE IF NOT EXISTS historical_evidence_records (
    evidence_id TEXT PRIMARY KEY,
    source_type TEXT NOT NULL,
    source_id TEXT NOT NULL,
    account_id TEXT,
    signal_id TEXT NOT NULL,
    instrument_key TEXT,
    trading_date TEXT NOT NULL,
    level_type TEXT,
    direction TEXT,
    signal_timestamp TEXT,
    candidate_symbol TEXT,
    instrument_token INTEGER,
    option_type TEXT,
    strike REAL,
    expiry TEXT,
    candidate_rank INTEGER,
    candidate_score REAL,
    entry_mode TEXT,
    signal_age_seconds REAL,
    opportunity_score REAL,
    reward_remaining_pct REAL,
    selection_score REAL,
    history_sample_size INTEGER,
    history_win_rate_pct REAL,
    history_profit_factor REAL,
    historical_expectancy_pct REAL,
    committee_confidence_pct REAL,
    committee_expectancy_pct REAL,
    portfolio_status TEXT,
    portfolio_reason TEXT,
    decision TEXT,
    execution TEXT,
    blocker TEXT,
    trade_status TEXT,
    entry_underlying_price REAL,
    entry_price REAL,
    exit_timestamp TEXT,
    exit_price REAL,
    exit_reason TEXT,
    mfe_points REAL,
    mae_points REAL,
    holding_minutes REAL,
    realized_pnl REAL,
    return_pct REAL,
    outcome_result TEXT,
    outcome_basis TEXT,
    entry_underlying_5m_close REAL,
    entry_ema10 REAL,
    entry_ema10_state TEXT,
    entry_ema10_timestamp TEXT,
    contract_entry_number INTEGER NOT NULL DEFAULT 1,
    signal_reentry_number INTEGER NOT NULL DEFAULT 0,
    same_signal_reentry INTEGER NOT NULL DEFAULT 0,
    shadow_execution_impact TEXT NOT NULL DEFAULT 'NONE',
    data_fidelity TEXT NOT NULL,
    data_source TEXT NOT NULL,
    evidence_completeness_pct REAL NOT NULL,
    missing_fields_json TEXT NOT NULL DEFAULT '[]',
    source_payload_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(source_type, source_id)
);

CREATE INDEX IF NOT EXISTS idx_historical_evidence_date
ON historical_evidence_records(trading_date, source_type);

CREATE INDEX IF NOT EXISTS idx_historical_evidence_signal
ON historical_evidence_records(signal_id, candidate_symbol);

CREATE INDEX IF NOT EXISTS idx_historical_evidence_setup
ON historical_evidence_records(level_type, direction, outcome_result);

CREATE INDEX IF NOT EXISTS idx_historical_evidence_reentry
ON historical_evidence_records(signal_reentry_number, same_signal_reentry);
"""


@dataclass(frozen=True)
class HistoricalEvidenceBuildReport:
    source_type: str
    source_rows: int
    records_written: int
    resolved_outcomes: int
    unresolved_outcomes: int
    reentries: int
    average_completeness_pct: float


@dataclass(frozen=True)
class HistoricalEvidenceRecord:
    evidence_id: str
    source_type: str
    source_id: str
    signal_id: str
    trading_date: str
    data_fidelity: str
    data_source: str
    account_id: str | None = None
    instrument_key: str | None = None
    level_type: str | None = None
    direction: str | None = None
    signal_timestamp: str | None = None
    candidate_symbol: str | None = None
    instrument_token: int | None = None
    option_type: str | None = None
    strike: float | None = None
    expiry: str | None = None
    candidate_rank: int | None = None
    candidate_score: float | None = None
    entry_mode: str | None = None
    signal_age_seconds: float | None = None
    opportunity_score: float | None = None
    reward_remaining_pct: float | None = None
    selection_score: float | None = None
    history_sample_size: int | None = None
    history_win_rate_pct: float | None = None
    history_profit_factor: float | None = None
    historical_expectancy_pct: float | None = None
    committee_confidence_pct: float | None = None
    committee_expectancy_pct: float | None = None
    portfolio_status: str | None = None
    portfolio_reason: str | None = None
    decision: str | None = None
    execution: str | None = None
    blocker: str | None = None
    trade_status: str | None = None
    entry_underlying_price: float | None = None
    entry_price: float | None = None
    exit_timestamp: str | None = None
    exit_price: float | None = None
    exit_reason: str | None = None
    mfe_points: float | None = None
    mae_points: float | None = None
    holding_minutes: float | None = None
    realized_pnl: float | None = None
    return_pct: float | None = None
    outcome_result: str | None = None
    outcome_basis: str | None = None
    entry_underlying_5m_close: float | None = None
    entry_ema10: float | None = None
    entry_ema10_state: str | None = None
    entry_ema10_timestamp: str | None = None
    contract_entry_number: int = 1
    signal_reentry_number: int = 0
    same_signal_reentry: bool = False
    shadow_execution_impact: str = "NONE"
    evidence_completeness_pct: float = 0.0
    missing_fields_json: str = "[]"
    source_payload_json: str = "{}"
    created_at: str = ""
    updated_at: str = ""

    def as_dict(self) -> dict[str, object]:
        row = asdict(self)
        row["same_signal_reentry"] = int(bool(self.same_signal_reentry))
        return row


class HistoricalEvidenceStore:
    """Additive evidence storage layered on the existing Red Bar database.

    This module deliberately owns only research evidence. It does not alter the
    Primary Decision Engine, Committee, Portfolio Manager, queue, or exit rules.
    """

    COLUMNS = (
        "evidence_id", "source_type", "source_id", "account_id", "signal_id",
        "instrument_key", "trading_date", "level_type", "direction",
        "signal_timestamp", "candidate_symbol", "instrument_token", "option_type",
        "strike", "expiry", "candidate_rank", "candidate_score", "entry_mode",
        "signal_age_seconds", "opportunity_score", "reward_remaining_pct",
        "selection_score", "history_sample_size", "history_win_rate_pct",
        "history_profit_factor", "historical_expectancy_pct",
        "committee_confidence_pct", "committee_expectancy_pct",
        "portfolio_status", "portfolio_reason", "decision", "execution", "blocker",
        "trade_status", "entry_underlying_price", "entry_price", "exit_timestamp",
        "exit_price", "exit_reason", "mfe_points", "mae_points", "holding_minutes",
        "realized_pnl", "return_pct", "outcome_result", "outcome_basis",
        "entry_underlying_5m_close", "entry_ema10", "entry_ema10_state",
        "entry_ema10_timestamp", "contract_entry_number", "signal_reentry_number",
        "same_signal_reentry", "shadow_execution_impact", "data_fidelity",
        "data_source", "evidence_completeness_pct", "missing_fields_json",
        "source_payload_json", "created_at", "updated_at",
    )

    def __init__(self, database) -> None:
        self.database = database
        self.path = Path(database.path)

    def initialize(self) -> None:
        self.database.initialize()
        with sqlite3.connect(self.path) as conn:
            conn.executescript(EVIDENCE_SCHEMA)
            conn.commit()

    def upsert(self, records: Iterable[HistoricalEvidenceRecord | dict[str, object]]) -> int:
        self.initialize()
        rows = [item.as_dict() if isinstance(item, HistoricalEvidenceRecord) else dict(item) for item in records]
        if not rows:
            return 0
        placeholders = ",".join("?" for _ in self.COLUMNS)
        updates = ",".join(
            f"{name}=excluded.{name}"
            for name in self.COLUMNS
            if name not in {"evidence_id", "source_type", "source_id", "created_at"}
        )
        sql = f"""
            INSERT INTO historical_evidence_records({','.join(self.COLUMNS)})
            VALUES({placeholders})
            ON CONFLICT(source_type, source_id) DO UPDATE SET
                {updates}
        """
        with sqlite3.connect(self.path) as conn:
            for row in rows:
                conn.execute(sql, tuple(row.get(name) for name in self.COLUMNS))
            conn.commit()
        return len(rows)

    def delete_source_day(
        self,
        *,
        source_type: str,
        instrument_key: str,
        trading_date: str,
    ) -> None:
        self.initialize()
        with sqlite3.connect(self.path) as conn:
            conn.execute(
                """
                DELETE FROM historical_evidence_records
                WHERE source_type=? AND instrument_key=? AND trading_date=?
                """,
                (source_type, instrument_key, trading_date),
            )
            conn.commit()

    def read(
        self,
        *,
        instrument_key: str | None = None,
        date_from: str | None = None,
        date_to: str | None = None,
        source_type: str | None = None,
        signal_id: str | None = None,
        limit: int = 5000,
    ) -> list[dict[str, object]]:
        self.initialize()
        clauses: list[str] = []
        values: list[object] = []
        if instrument_key:
            clauses.append("instrument_key=?")
            values.append(instrument_key)
        if date_from:
            clauses.append("trading_date>=?")
            values.append(date_from)
        if date_to:
            clauses.append("trading_date<=?")
            values.append(date_to)
        if source_type:
            clauses.append("source_type=?")
            values.append(source_type)
        if signal_id:
            clauses.append("signal_id=?")
            values.append(signal_id)
        where = "WHERE " + " AND ".join(clauses) if clauses else ""
        values.append(max(1, int(limit)))
        with sqlite3.connect(self.path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                f"""
                SELECT * FROM historical_evidence_records
                {where}
                ORDER BY trading_date, signal_timestamp, candidate_rank, evidence_id
                LIMIT ?
                """,
                tuple(values),
            ).fetchall()
        result: list[dict[str, object]] = []
        for raw in rows:
            row = dict(raw)
            try:
                row["missing_fields"] = json.loads(str(row.get("missing_fields_json") or "[]"))
            except Exception:
                row["missing_fields"] = []
            try:
                row["source_payload"] = json.loads(str(row.get("source_payload_json") or "{}"))
            except Exception:
                row["source_payload"] = {}
            result.append(row)
        return result


class HistoricalEvidenceService:
    """Build canonical, point-in-time research evidence from existing records.

    Evidence is descriptive only. Missing data stays NULL and is explicitly
    reported; the service never fabricates bid/ask, IV, Greeks, EMA10, or outcomes.
    """

    CORE_FIELDS = (
        "signal_id", "instrument_key", "trading_date", "level_type", "direction",
        "candidate_symbol", "option_type", "candidate_score", "opportunity_score",
        "selection_score", "decision", "execution",
    )
    TRACKED_RESEARCH_FIELDS = CORE_FIELDS + (
        "candidate_rank", "entry_price", "entry_underlying_5m_close", "entry_ema10",
        "entry_ema10_state", "mfe_points", "mae_points", "outcome_result",
    )

    UNDERLYING_KEYS = {
        "NIFTY 50": "NSE_INDEX|Nifty 50",
        "BANK NIFTY": "NSE_INDEX|Nifty Bank",
        "NIFTY BANK": "NSE_INDEX|Nifty Bank",
    }

    def __init__(self, database) -> None:
        self.database = database
        self.store = HistoricalEvidenceStore(database)

    @staticmethod
    def _int(value: object) -> int | None:
        try:
            if value is None or pd.isna(value):
                return None
            return int(value)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _timestamp(value: object) -> pd.Timestamp | None:
        if value in (None, ""):
            return None
        try:
            ts = pd.Timestamp(value)
            if pd.isna(ts):
                return None
            if ts.tzinfo is None:
                ts = ts.tz_localize("Asia/Kolkata")
            else:
                ts = ts.tz_convert("Asia/Kolkata")
            return ts
        except Exception:
            return None

    @classmethod
    def _trading_date(cls, value: object) -> str | None:
        ts = cls._timestamp(value)
        return ts.date().isoformat() if ts is not None else None

    @classmethod
    def _holding_minutes(cls, entry: object, exit_value: object) -> float | None:
        start = cls._timestamp(entry)
        end = cls._timestamp(exit_value)
        if start is None or end is None or end < start:
            return None
        return round((end - start).total_seconds() / 60.0, 2)

    @staticmethod
    def _return_pct(entry: float | None, exit_price: float | None) -> float | None:
        if entry is None or exit_price is None or entry <= 0:
            return None
        return round((exit_price - entry) / entry * 100.0, 4)

    @staticmethod
    def _outcome(return_pct: float | None, status: str | None = None) -> str:
        if str(status or "").upper() == "OPEN":
            return "OPEN"
        if return_pct is None:
            return "UNKNOWN"
        if return_pct > 0:
            return "WIN"
        if return_pct < 0:
            return "LOSS"
        return "BREAKEVEN"

    @staticmethod
    def _stable_id(prefix: str, source_id: str) -> str:
        digest = hashlib.sha1(source_id.encode("utf-8")).hexdigest()[:20].upper()
        return f"HE-{prefix}-{digest}"

    @classmethod
    def _completeness(cls, row: dict[str, object]) -> tuple[float, list[str]]:
        missing = [name for name in cls.TRACKED_RESEARCH_FIELDS if row.get(name) is None]
        core_present = sum(row.get(name) is not None for name in cls.CORE_FIELDS)
        pct = round(core_present / len(cls.CORE_FIELDS) * 100.0, 2)
        return pct, missing

    @staticmethod
    def _payload(value: object) -> dict[str, object]:
        if isinstance(value, dict):
            return dict(value)
        if hasattr(value, "as_dict"):
            try:
                return dict(value.as_dict())
            except Exception:
                pass
        if hasattr(value, "__dict__"):
            return dict(value.__dict__)
        return {}

    def build_paper_execution_evidence(
        self,
        *,
        account_id: str = "PAPER-STD",
        date_from: str | None = None,
        date_to: str | None = None,
    ) -> HistoricalEvidenceBuildReport:
        orders = list(self.database.read_paper_execution_orders(account_id))
        orders.sort(key=lambda row: str(row.get("entry_timestamp") or ""))
        signal_ids = [str(row.get("signal_id") or "") for row in orders]
        signals = self.database.read_signal_attempts_by_ids(signal_ids)

        contract_counts: dict[tuple[str, int], int] = {}
        signal_counts: dict[tuple[str, str, int], int] = {}
        records: list[HistoricalEvidenceRecord] = []

        for order in orders:
            signal_id = str(order.get("signal_id") or "")
            token = int(order.get("instrument_token") or 0)
            contract_key = (account_id, token)
            signal_key = (account_id, signal_id, token)
            contract_counts[contract_key] = contract_counts.get(contract_key, 0) + 1
            signal_counts[signal_key] = signal_counts.get(signal_key, 0) + 1

            signal = signals.get(signal_id, {})
            entry_ts = order.get("entry_timestamp")
            trading_date = str(signal.get("trading_date") or self._trading_date(entry_ts) or "")
            if date_from and trading_date < date_from:
                continue
            if date_to and trading_date > date_to:
                continue

            instrument_key = str(signal.get("instrument_key") or "") or self.UNDERLYING_KEYS.get(
                str(order.get("underlying_name") or "").upper()
            )
            entry_price = safe_float(order.get("entry_price"))
            exit_price = safe_float(order.get("exit_price"))
            return_pct = self._return_pct(entry_price, exit_price)
            status = str(order.get("status") or "UNKNOWN").upper()
            outcome = self._outcome(return_pct, status)

            source_id = str(order.get("order_id") or "")
            now = datetime.now().astimezone().isoformat()
            row: dict[str, object] = {
                "signal_id": signal_id,
                "instrument_key": instrument_key,
                "trading_date": trading_date,
                "level_type": signal.get("level_type"),
                "direction": signal.get("direction"),
                "candidate_symbol": order.get("tradingsymbol"),
                "option_type": order.get("option_type"),
                "candidate_rank": self._int(order.get("candidate_rank")),
                "candidate_score": safe_float(order.get("candidate_score")),
                "opportunity_score": safe_float(order.get("opportunity_score")),
                "selection_score": safe_float(order.get("selection_score")),
                "decision": "APPROVED",
                "execution": "EXECUTED",
                "entry_price": entry_price,
                "entry_underlying_5m_close": safe_float(order.get("entry_underlying_5m_close")),
                "entry_ema10": safe_float(order.get("entry_ema10")),
                "entry_ema10_state": order.get("entry_ema10_state"),
                "mfe_points": safe_float(order.get("mfe_points")),
                "mae_points": safe_float(order.get("mae_points")),
                "outcome_result": outcome,
            }
            completeness, missing = self._completeness(row)
            data_fidelity = (
                "LIVE_PAPER_CAPTURE"
                if order.get("market_data_provider")
                else "PAPER_CAPTURE_PARTIAL"
            )
            data_source = (
                f"{order.get('market_data_provider') or 'UNKNOWN'}->"
                f"{order.get('execution_provider') or 'PAPER'}"
            )
            records.append(HistoricalEvidenceRecord(
                evidence_id=self._stable_id("PAPER", source_id),
                source_type="PAPER_EXECUTION",
                source_id=source_id,
                account_id=account_id,
                signal_id=signal_id,
                instrument_key=instrument_key,
                trading_date=trading_date,
                level_type=str(signal.get("level_type") or "") or None,
                direction=str(signal.get("direction") or "") or None,
                signal_timestamp=str(signal.get("confirmation_timestamp") or "") or None,
                candidate_symbol=str(order.get("tradingsymbol") or "") or None,
                instrument_token=token or None,
                option_type=str(order.get("option_type") or "") or None,
                strike=safe_float(order.get("strike")),
                expiry=str(order.get("expiry") or "") or None,
                candidate_rank=self._int(order.get("candidate_rank")),
                candidate_score=safe_float(order.get("candidate_score")),
                entry_mode=str(order.get("entry_mode") or "") or None,
                signal_age_seconds=safe_float(order.get("signal_age_at_entry")),
                opportunity_score=safe_float(order.get("opportunity_score")),
                reward_remaining_pct=safe_float(order.get("reward_remaining_pct")),
                selection_score=safe_float(order.get("selection_score")),
                history_sample_size=self._int(order.get("historical_sample_size")),
                history_win_rate_pct=safe_float(order.get("historical_win_rate_pct")),
                history_profit_factor=safe_float(order.get("historical_profit_factor")),
                historical_expectancy_pct=safe_float(order.get("historical_expectancy_pct")),
                committee_confidence_pct=safe_float(order.get("execution_probability_pct")),
                committee_expectancy_pct=None,
                portfolio_status="ADMITTED",
                portfolio_reason="PAPER_EXECUTION_OPENED",
                decision="APPROVED",
                execution="EXECUTED",
                blocker="NONE",
                trade_status=status,
                entry_underlying_price=safe_float(order.get("underlying_price_entry")),
                entry_price=entry_price,
                exit_timestamp=str(order.get("exit_timestamp") or "") or None,
                exit_price=exit_price,
                exit_reason=str(order.get("exit_reason") or "") or None,
                mfe_points=safe_float(order.get("mfe_points")),
                mae_points=safe_float(order.get("mae_points")),
                holding_minutes=self._holding_minutes(entry_ts, order.get("exit_timestamp")),
                realized_pnl=safe_float(order.get("realized_pnl")),
                return_pct=return_pct,
                outcome_result=outcome,
                outcome_basis=("PAPER_EXECUTION" if status == "CLOSED" else "OPEN_POSITION"),
                entry_underlying_5m_close=safe_float(order.get("entry_underlying_5m_close")),
                entry_ema10=safe_float(order.get("entry_ema10")),
                entry_ema10_state=str(order.get("entry_ema10_state") or "") or None,
                entry_ema10_timestamp=str(order.get("entry_ema10_timestamp") or "") or None,
                contract_entry_number=contract_counts[contract_key],
                signal_reentry_number=max(0, signal_counts[signal_key] - 1),
                same_signal_reentry=signal_counts[signal_key] > 1,
                shadow_execution_impact="NONE",
                data_fidelity=data_fidelity,
                data_source=data_source,
                evidence_completeness_pct=completeness,
                missing_fields_json=json.dumps(missing, sort_keys=True),
                source_payload_json=json.dumps(
                    {"order": order, "signal": signal}, sort_keys=True, default=str
                ),
                created_at=now,
                updated_at=now,
            ))

        written = self.store.upsert(records)
        return self._report("PAPER_EXECUTION", len(orders), records, written)

    def ingest_replay_result(
        self,
        *,
        instrument_key: str,
        result,
    ) -> HistoricalEvidenceBuildReport:
        trading_date = str(getattr(result, "trading_date", ""))
        if hasattr(getattr(result, "trading_date", None), "isoformat"):
            trading_date = result.trading_date.isoformat()
        self.store.delete_source_day(
            source_type="HISTORICAL_REPLAY",
            instrument_key=instrument_key,
            trading_date=trading_date,
        )

        raw_rows = list(getattr(result, "rows", ()) or ())
        records: list[HistoricalEvidenceRecord] = []
        for raw in raw_rows:
            row = self._payload(raw)
            signal_id = str(row.get("signal_id") or "")
            candidate_symbol = str(row.get("candidate_symbol") or "") or None
            source_identity = "|".join((
                signal_id,
                str(row.get("timestamp") or ""),
                candidate_symbol or "NO_CANDIDATE",
                str(row.get("candidate_rank") or 0),
            ))
            entry_price = safe_float(row.get("option_entry_price"))
            exit_price = safe_float(row.get("option_exit_price"))
            return_pct = safe_float(row.get("option_return_pct"))
            if return_pct is None:
                return_pct = self._return_pct(entry_price, exit_price)
            outcome = str(row.get("outcome_result") or "UNKNOWN").upper()
            trade_status = "CLOSED" if exit_price is not None else "EVALUATED"

            canonical: dict[str, object] = {
                "signal_id": signal_id,
                "instrument_key": instrument_key,
                "trading_date": trading_date,
                "level_type": row.get("level_type"),
                "direction": row.get("direction"),
                "candidate_symbol": candidate_symbol,
                "option_type": row.get("option_side"),
                "candidate_rank": self._int(row.get("candidate_rank")),
                "candidate_score": safe_float(row.get("candidate_score")),
                "opportunity_score": safe_float(row.get("opportunity_health")),
                "selection_score": None,
                "decision": row.get("decision"),
                "execution": row.get("execution"),
                "entry_price": entry_price,
                "entry_underlying_5m_close": safe_float(row.get("ema10_5m_close")),
                "entry_ema10": safe_float(row.get("ema10_5m_value")),
                "entry_ema10_state": row.get("ema10_5m_state"),
                "mfe_points": safe_float(row.get("mfe_points")),
                "mae_points": safe_float(row.get("mae_points")),
                "outcome_result": outcome,
            }
            completeness, missing = self._completeness(canonical)
            now = datetime.now().astimezone().isoformat()
            records.append(HistoricalEvidenceRecord(
                evidence_id=self._stable_id("REPLAY", source_identity),
                source_type="HISTORICAL_REPLAY",
                source_id=source_identity,
                signal_id=signal_id,
                instrument_key=instrument_key,
                trading_date=trading_date,
                level_type=str(row.get("level_type") or "") or None,
                direction=str(row.get("direction") or "") or None,
                signal_timestamp=str(row.get("timestamp") or "") or None,
                candidate_symbol=candidate_symbol,
                option_type=str(row.get("option_side") or "") or None,
                candidate_rank=self._int(row.get("candidate_rank")),
                candidate_score=safe_float(row.get("candidate_score")),
                opportunity_score=safe_float(row.get("opportunity_health")),
                committee_confidence_pct=safe_float(row.get("final_confidence_pct")),
                committee_expectancy_pct=safe_float(row.get("expectancy_pct")),
                portfolio_status=str(row.get("portfolio_status") or "") or None,
                portfolio_reason=str(row.get("portfolio_reason") or "") or None,
                decision=str(row.get("decision") or "") or None,
                execution=str(row.get("execution") or "") or None,
                blocker=str(row.get("blocker") or "") or None,
                trade_status=trade_status,
                entry_price=entry_price,
                exit_price=exit_price,
                exit_reason=str(row.get("exit_reason") or "") or None,
                mfe_points=safe_float(row.get("mfe_points")),
                mae_points=safe_float(row.get("mae_points")),
                return_pct=return_pct,
                outcome_result=outcome,
                outcome_basis=str(row.get("outcome_basis") or "") or None,
                entry_underlying_5m_close=safe_float(row.get("ema10_5m_close")),
                entry_ema10=safe_float(row.get("ema10_5m_value")),
                entry_ema10_state=str(row.get("ema10_5m_state") or "") or None,
                entry_ema10_timestamp=str(row.get("ema10_5m_timestamp") or "") or None,
                shadow_execution_impact="NONE",
                data_fidelity=str(row.get("data_fidelity") or getattr(result, "data_fidelity", "UNKNOWN")),
                data_source=str(getattr(result, "data_source", "HISTORICAL_REPLAY") or "HISTORICAL_REPLAY"),
                evidence_completeness_pct=completeness,
                missing_fields_json=json.dumps(missing, sort_keys=True),
                source_payload_json=json.dumps(row, sort_keys=True, default=str),
                created_at=now,
                updated_at=now,
            ))

        written = self.store.upsert(records)
        return self._report("HISTORICAL_REPLAY", len(raw_rows), records, written)

    @staticmethod
    def _report(
        source_type: str,
        source_rows: int,
        records: list[HistoricalEvidenceRecord],
        written: int,
    ) -> HistoricalEvidenceBuildReport:
        resolved = sum(
            str(item.outcome_result or "").upper() in {"WIN", "LOSS", "BREAKEVEN"}
            for item in records
        )
        reentries = sum(bool(item.same_signal_reentry) for item in records)
        average = (
            sum(float(item.evidence_completeness_pct) for item in records) / len(records)
            if records else 0.0
        )
        return HistoricalEvidenceBuildReport(
            source_type=source_type,
            source_rows=source_rows,
            records_written=written,
            resolved_outcomes=resolved,
            unresolved_outcomes=max(0, len(records) - resolved),
            reentries=reentries,
            average_completeness_pct=round(average, 2),
        )
