from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path
import sqlite3
import time

import pandas as pd


@dataclass(frozen=True)
class ReplayDiagnosticStage:
    stage: str
    status: str
    detail: str
    duration_ms: float = 0.0

    def as_dict(self) -> dict[str, object]:
        return {
            "Stage": self.stage,
            "Status": self.status,
            "Detail": self.detail,
            "Duration ms": round(float(self.duration_ms), 2),
        }


@dataclass(frozen=True)
class ReplayDiagnosticsReport:
    trading_date: date
    instrument_key: str
    underlying_rows: int
    resolved_expiry: str | None
    expired_expiries_found: int
    parsed_expiries_found: int
    expiry_resolution_rule: str
    expiry_previous: str | None
    expiry_next: str | None
    expiry_candidates: tuple[str, ...]
    expiry_resolution_source: str
    expiry_probed_dates: tuple[str, ...]
    provider_contracts_found: int
    stored_manifest_contracts: int
    live_snapshots_found: int
    data_source: str
    replay_fidelity: str
    replay_ready: bool
    database_status: str
    database_journal_mode: str
    database_size_mb: float
    total_duration_ms: float
    stages: tuple[ReplayDiagnosticStage, ...]
    error: str = ""

    def as_dict(self) -> dict[str, object]:
        return {
            "Replay Date": self.trading_date.isoformat(),
            "Instrument Key": self.instrument_key,
            "Underlying Rows": self.underlying_rows,
            "Resolved Expiry": self.resolved_expiry or "—",
            "Expired Expiries Found": self.expired_expiries_found,
            "Parsed Expiries": self.parsed_expiries_found,
            "Expiry Rule": self.expiry_resolution_rule,
            "Previous Expiry": self.expiry_previous or "—",
            "Next Eligible Expiry": self.expiry_next or "—",
            "Expiry Candidates": ", ".join(self.expiry_candidates) if self.expiry_candidates else "—",
            "Expiry Resolution Source": self.expiry_resolution_source,
            "Probed Expiry Dates": ", ".join(self.expiry_probed_dates) if self.expiry_probed_dates else "—",
            "Provider Contracts Found": self.provider_contracts_found,
            "Stored Manifest Contracts": self.stored_manifest_contracts,
            "Live Snapshots Found": self.live_snapshots_found,
            "Replay Source": self.data_source,
            "Replay Fidelity": self.replay_fidelity,
            "Replay Ready": "YES" if self.replay_ready else "NO",
            "Database": self.database_status,
            "SQLite Journal Mode": self.database_journal_mode,
            "Database Size MB": round(self.database_size_mb, 2),
            "Diagnostics Duration ms": round(self.total_duration_ms, 2),
            "Error": self.error or "—",
        }


class ReplayDiagnosticsService:
    """Read-only observability for historical replay readiness.

    The service deliberately does not modify strategy state, committee policy,
    portfolio policy, queue state or historical caches. Provider calls are used
    only to diagnose expiry/contract discovery when explicitly requested by the UI.
    """

    def __init__(self, option_sync, historical, database=None) -> None:
        self.option_sync = option_sync
        self.historical = historical
        self.database = database

    @staticmethod
    def _timed(fn):
        started = time.perf_counter()
        value = fn()
        return value, (time.perf_counter() - started) * 1000.0

    def _database_health(self) -> tuple[str, str, float, ReplayDiagnosticStage]:
        if self.database is None:
            return "UNAVAILABLE", "UNKNOWN", 0.0, ReplayDiagnosticStage(
                "Database", "WARN", "Database facade was not supplied to diagnostics."
            )
        path = Path(self.database.path)
        if not path.exists():
            return "MISSING", "UNKNOWN", 0.0, ReplayDiagnosticStage(
                "Database", "FAIL", f"SQLite file does not exist: {path}"
            )
        started = time.perf_counter()
        try:
            with sqlite3.connect(path, timeout=2.0) as conn:
                mode_row = conn.execute("PRAGMA journal_mode").fetchone()
                conn.execute("SELECT 1").fetchone()
            mode = str(mode_row[0] if mode_row else "UNKNOWN").upper()
            status = "PASS"
            detail = f"SQLite reachable; journal_mode={mode}."
        except sqlite3.OperationalError as exc:
            mode = "UNKNOWN"
            status = "LOCKED" if "locked" in str(exc).lower() else "FAIL"
            detail = f"SQLite health probe failed: {exc}"
        elapsed = (time.perf_counter() - started) * 1000.0
        size_mb = path.stat().st_size / (1024.0 * 1024.0)
        return status, mode, size_mb, ReplayDiagnosticStage("Database", status, detail, elapsed)

    def inspect_day(self, instrument_key: str, trading_date: date, *, probe_provider: bool = True) -> ReplayDiagnosticsReport:
        total_started = time.perf_counter()
        stages: list[ReplayDiagnosticStage] = []
        error = ""

        try:
            underlying, elapsed = self._timed(
                lambda: self.historical.read_day(instrument_key, trading_date, interval_minutes=1)
            )
            underlying_rows = int(len(underlying))
            stages.append(ReplayDiagnosticStage(
                "Underlying Data",
                "PASS" if underlying_rows else "FAIL",
                f"{underlying_rows} one-minute underlying rows available.",
                elapsed,
            ))
        except Exception as exc:
            underlying_rows = 0
            error = f"Underlying read failed: {type(exc).__name__}: {exc}"
            stages.append(ReplayDiagnosticStage("Underlying Data", "FAIL", error))

        manifest = self.option_sync.store.read_manifest(instrument_key, trading_date)
        stored_contracts = len([r for r in (manifest.get("contracts") or []) if isinstance(r, dict)])
        manifest_expiry = str(manifest.get("expiry") or "") or None
        stages.append(ReplayDiagnosticStage(
            "Stored Option Manifest",
            "PASS" if stored_contracts else "WARN",
            f"Stored contracts={stored_contracts}; stored expiry={manifest_expiry or 'none'}.",
        ))

        live_snapshots = 0
        try:
            snapshots, elapsed = self._timed(lambda: self.option_sync._live_snapshots(instrument_key, trading_date))
            live_snapshots = len(snapshots)
            stages.append(ReplayDiagnosticStage(
                "Live Market Capture",
                "PASS" if live_snapshots else "INFO",
                f"ONLINE option-chain snapshots found={live_snapshots}.",
                elapsed,
            ))
        except Exception as exc:
            stages.append(ReplayDiagnosticStage(
                "Live Market Capture", "WARN", f"Live snapshot inspection failed: {type(exc).__name__}: {exc}"
            ))

        expiries_found = 0
        parsed_expiries = 0
        expiry_rule = "UNKNOWN"
        expiry_previous = None
        expiry_next = None
        expiry_candidates: tuple[str, ...] = ()
        expiry_resolution_source = "MANIFEST" if manifest_expiry else "UNKNOWN"
        expiry_probed_dates: tuple[str, ...] = ()
        selected_expiry = manifest_expiry
        provider_contracts = 0
        if probe_provider:
            try:
                expiries, elapsed = self._timed(lambda: self.option_sync.provider.expired_option_expiries(instrument_key))
                expiries_found = len(expiries or [])
                stages.append(ReplayDiagnosticStage(
                    "Expired Expiry Discovery",
                    "PASS" if expiries_found else "FAIL",
                    f"Provider returned {expiries_found} expired expiries.",
                    elapsed,
                ))
                resolution, elapsed = self._timed(
                    lambda: self.option_sync.expiry_resolution_details(instrument_key, trading_date)
                )
                selected_expiry = resolution.get("selected")
                parsed_expiries = int(resolution.get("parsed_count") or 0)
                expiry_rule = str(resolution.get("rule") or "UNKNOWN")
                expiry_previous = resolution.get("previous")
                expiry_next = resolution.get("next")
                expiry_candidates = tuple(resolution.get("candidate_expiries") or ())
                expiry_resolution_source = str(resolution.get("resolution_source") or "UNKNOWN")
                expiry_probed_dates = tuple(resolution.get("probed_dates") or ())
                unparsed_count = int(resolution.get("unparsed_count") or 0)
                stages.append(ReplayDiagnosticStage(
                    "Expiry Resolution",
                    "PASS" if selected_expiry else "FAIL",
                    (f"rule={expiry_rule}; trading_date={trading_date.isoformat()}; "
                     f"parsed={parsed_expiries}/{expiries_found}; previous={expiry_previous or 'none'}; "
                     f"next={expiry_next or 'none'}; selected={selected_expiry or 'none'}; "
                     f"source={expiry_resolution_source}; candidates={','.join(expiry_candidates) if expiry_candidates else 'none'}; "
                     f"probed={','.join(expiry_probed_dates) if expiry_probed_dates else 'none'}; unparsed={unparsed_count}."),
                    elapsed,
                ))
                if selected_expiry:
                    contracts, elapsed = self._timed(
                        lambda: self.option_sync.provider.expired_option_contracts(instrument_key, selected_expiry)
                    )
                    provider_contracts = len(contracts or [])
                    stages.append(ReplayDiagnosticStage(
                        "Option Contract Discovery",
                        "PASS" if provider_contracts else "FAIL",
                        f"Provider returned {provider_contracts} option contracts for expiry {selected_expiry}.",
                        elapsed,
                    ))
                else:
                    stages.append(ReplayDiagnosticStage(
                        "Option Contract Discovery", "BLOCKED", "Skipped because no eligible historical expiry was resolved."
                    ))
            except Exception as exc:
                provider_error = f"{type(exc).__name__}: {exc}"
                error = error or provider_error
                stages.append(ReplayDiagnosticStage("Provider Discovery", "FAIL", provider_error))
        else:
            stages.append(ReplayDiagnosticStage(
                "Provider Discovery", "SKIPPED", "Provider probe disabled; diagnostics are local-cache only."
            ))

        try:
            coverage, elapsed = self._timed(lambda: self.option_sync.validate_day(instrument_key, trading_date))
            stages.append(ReplayDiagnosticStage(
                "Replay Readiness",
                "PASS" if coverage.replay_ready else "FAIL",
                f"source={coverage.data_source}; fidelity={coverage.fidelity}; "
                f"contract={coverage.contract_coverage_pct:.1f}%; candle={coverage.candle_coverage_pct:.1f}%; "
                f"OI={coverage.oi_coverage_pct:.1f}%.",
                elapsed,
            ))
        except Exception as exc:
            coverage = None
            error = error or f"Coverage validation failed: {type(exc).__name__}: {exc}"
            stages.append(ReplayDiagnosticStage("Replay Readiness", "FAIL", error))

        db_status, db_mode, db_size, db_stage = self._database_health()
        stages.append(db_stage)

        total_ms = (time.perf_counter() - total_started) * 1000.0
        return ReplayDiagnosticsReport(
            trading_date=trading_date,
            instrument_key=instrument_key,
            underlying_rows=underlying_rows,
            resolved_expiry=selected_expiry,
            expired_expiries_found=expiries_found,
            parsed_expiries_found=parsed_expiries,
            expiry_resolution_rule=expiry_rule,
            expiry_previous=expiry_previous,
            expiry_next=expiry_next,
            expiry_candidates=expiry_candidates,
            expiry_resolution_source=expiry_resolution_source,
            expiry_probed_dates=expiry_probed_dates,
            provider_contracts_found=provider_contracts,
            stored_manifest_contracts=stored_contracts,
            live_snapshots_found=live_snapshots,
            data_source=coverage.data_source if coverage is not None else "UNKNOWN",
            replay_fidelity=coverage.fidelity if coverage is not None else "UNKNOWN",
            replay_ready=bool(coverage.replay_ready) if coverage is not None else False,
            database_status=db_status,
            database_journal_mode=db_mode,
            database_size_mb=db_size,
            total_duration_ms=total_ms,
            stages=tuple(stages),
            error=error,
        )
