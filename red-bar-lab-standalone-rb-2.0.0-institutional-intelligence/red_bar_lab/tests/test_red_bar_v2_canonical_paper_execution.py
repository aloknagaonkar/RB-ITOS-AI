from __future__ import annotations

from dataclasses import replace
from datetime import timedelta
from pathlib import Path
import sqlite3

import pytest

from red_bar_lab.config import RedBarSettings
from red_bar_lab.domain.red_bar_v2 import OptionSide
from red_bar_lab.services.red_bar_v2_canonical import (
    RedBarV2CanonicalPersistenceService,
    SQLiteRedBarV2CanonicalRepository,
)
from red_bar_lab.services.red_bar_v2_canonical.paper_execution_adapter import PaperAdapterResult
from red_bar_lab.services.red_bar_v2_canonical.paper_execution_identity import build_command_id, build_execution_id
from red_bar_lab.services.red_bar_v2_canonical.paper_execution_ledger import StrictSQLiteCanonicalPaperExecutionRepository
from red_bar_lab.services.red_bar_v2_canonical.paper_execution_models import (
    CanonicalPaperContract,
    CanonicalPaperExecutionCommand,
    PaperExecutionOutcome,
    PaperExecutionState,
)
from red_bar_lab.services.red_bar_v2_canonical.paper_execution_observability import SQLiteCanonicalPaperExecutionObservabilityRepository
from red_bar_lab.services.red_bar_v2_canonical.paper_execution_service import CANONICAL_PAPER_WORKER_OWNER
from red_bar_lab.services.red_bar_v2_canonical.paper_replay_guard import ReplayGuardedCanonicalPaperService
from red_bar_lab.services.red_bar_v2_canonical.reservation_repository import SQLiteCanonicalReservationRepository
from red_bar_lab.services.red_bar_v2_canonical.reservation_service import RedBarV2CanonicalReservationService
from red_bar_lab.tests.red_bar_v2_persistence_fixtures import RESOLVED_AT, UNDERLYING, make_resolution


class FixedSelector:
    def __init__(self, contract):
        self.contract = contract

    def select(self, **kwargs):
        return self.contract


class FakePaperAdapter:
    def __init__(self, *, accepted=True, uncertain=False):
        self.accepted = accepted
        self.uncertain = uncertain
        self.submissions = 0
        self.rows = {}

    def lookup(self, *, execution_id):
        return self.rows.get(execution_id)

    def submit(self, *, command):
        self.submissions += 1
        result = PaperAdapterResult(
            accepted=self.accepted,
            uncertain=self.uncertain,
            reason_code="PAPER_ACCEPTED" if self.accepted else "PAPER_REJECTED",
            paper_order_id=None if self.uncertain else "PAPER-1",
        )
        if not self.uncertain:
            self.rows[command.execution_id] = result
        return result


def _database(path: Path):
    resolution, parity = make_resolution()
    RedBarV2CanonicalPersistenceService(
        SQLiteRedBarV2CanonicalRepository(path),
        clock=lambda: RESOLVED_AT,
    ).persist(resolution=resolution, parity=parity, instrument_key=UNDERLYING)
    assert resolution.section_3 is not None
    return resolution.section_3


def _contract(bundle):
    return CanonicalPaperContract(
        instrument_token=123,
        instrument_key="NFO|123",
        tradingsymbol="NIFTYTESTCE",
        exchange="NFO",
        option_side=bundle.option_side,
        strike=25000.0,
        expiry=bundle.trading_date,
        lot_size=75,
        selected_at=bundle.created_at,
        quote_timestamp=bundle.created_at,
        last_price=100.0,
        best_bid=99.5,
        best_ask=100.5,
    )


def _service(path: Path, *, enabled=True, mode="PAPER_CANARY", adapter=None, contract=None):
    bundle = _database(path)
    reservations = RedBarV2CanonicalReservationService(
        SQLiteCanonicalReservationRepository(path),
        enabled=True,
        lease_seconds=30,
    )
    ledger = StrictSQLiteCanonicalPaperExecutionRepository(path)
    adapter = adapter or FakePaperAdapter()
    service = ReplayGuardedCanonicalPaperService(
        database_path=path,
        repository=ledger,
        reservation_service=reservations,
        selector=FixedSelector(contract or _contract(bundle)),
        adapter=adapter,
        enabled=enabled,
        mode=mode,
    )
    return bundle, service, adapter, ledger


def test_configuration_defaults_are_fail_closed(monkeypatch):
    monkeypatch.delenv("RED_BAR_V2_CANONICAL_PAPER_EXECUTION_ENABLED", raising=False)
    monkeypatch.delenv("RED_BAR_V2_CANONICAL_PAPER_EXECUTION_MODE", raising=False)
    settings = RedBarSettings.from_env()
    assert settings.red_bar_v2_canonical_paper_execution_enabled is False
    assert settings.red_bar_v2_canonical_paper_execution_mode == "OBSERVE_ONLY"
    monkeypatch.setenv("RED_BAR_V2_CANONICAL_PAPER_EXECUTION_MODE", "UNKNOWN")
    assert RedBarSettings.from_env().red_bar_v2_canonical_paper_execution_mode == "INVALID"


def test_observe_only_creates_no_mutations(tmp_path: Path):
    path = tmp_path / "db.sqlite"
    bundle, service, adapter, _ = _service(path, mode="OBSERVE_ONLY")
    result = service.execute(bundle_id=bundle.bundle_id, spot_price=25000.0, requested_at=bundle.created_at)
    assert result.outcome is PaperExecutionOutcome.OBSERVE_ONLY
    assert adapter.submissions == 0
    with sqlite3.connect(path) as conn:
        assert conn.execute("SELECT COUNT(*) FROM canonical_red_bar_v2_bundle_reservations").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM canonical_red_bar_v2_paper_commands").fetchone()[0] == 0


def test_contract_and_command_identities_are_strict(tmp_path: Path):
    bundle = _database(tmp_path / "db.sqlite")
    contract = _contract(bundle)
    execution_id = build_execution_id(
        bundle_id=bundle.bundle_id,
        reservation_id="RESERVATION",
        contract_instrument_key=contract.instrument_key,
        quantity=75,
        order_side="BUY",
        order_type="MARKET",
        limit_price=None,
    )
    command = CanonicalPaperExecutionCommand(
        command_id=build_command_id(execution_id=execution_id, created_at=bundle.created_at),
        execution_id=execution_id,
        reservation_id="RESERVATION",
        bundle_id=bundle.bundle_id,
        signal_id=bundle.signal_id,
        idempotency_key=bundle.idempotency_key,
        strategy_id=bundle.strategy_id,
        strategy_version=bundle.strategy_version,
        instrument_key=bundle.instrument_key or "",
        trading_date=bundle.trading_date,
        direction=bundle.direction,
        option_side=bundle.option_side,
        entry_type=bundle.entry_type,
        signal_timestamp=bundle.evaluation_timestamp,
        reservation_owner=CANONICAL_PAPER_WORKER_OWNER,
        reservation_expiry=bundle.created_at + timedelta(seconds=30),
        contract=contract,
        quantity=75,
        order_side="BUY",
        order_type="MARKET",
        limit_price=None,
        created_at=bundle.created_at,
    )
    with pytest.raises(ValueError, match="command_id"):
        replace(command, command_id="TAMPERED")
    with pytest.raises(ValueError, match="timezone-aware"):
        replace(command, created_at=command.created_at.replace(tzinfo=None))
    with pytest.raises(ValueError, match="option side mismatch"):
        replace(command, contract=replace(contract, option_side=OptionSide.PE if bundle.option_side is OptionSide.CE else OptionSide.CE))


def test_canary_fills_releases_and_replays_without_new_lease(tmp_path: Path):
    path = tmp_path / "db.sqlite"
    bundle, service, adapter, ledger = _service(path)
    first = service.execute(bundle_id=bundle.bundle_id, spot_price=25000.0, requested_at=bundle.created_at)
    second = service.execute(bundle_id=bundle.bundle_id, spot_price=25000.0, requested_at=bundle.created_at + timedelta(seconds=1))
    assert first.outcome is PaperExecutionOutcome.SUBMISSION_ACCEPTED
    assert first.state is PaperExecutionState.PAPER_FILLED
    assert second.outcome is PaperExecutionOutcome.IDEMPOTENT_REPLAY
    assert adapter.submissions == 1
    assert ledger.get_verified(execution_id=first.command.execution_id).state is PaperExecutionState.PAPER_FILLED
    with sqlite3.connect(path) as conn:
        assert conn.execute("SELECT COUNT(*) FROM canonical_red_bar_v2_paper_commands").fetchone()[0] == 1
        assert conn.execute("SELECT COUNT(*) FROM canonical_red_bar_v2_bundle_reservations WHERE state='RESERVED'").fetchone()[0] == 0


def test_wrong_side_releases_and_uncertain_keeps_reservation(tmp_path: Path):
    path = tmp_path / "wrong.db"
    bundle = _database(path)
    wrong = replace(_contract(bundle), option_side=OptionSide.PE if bundle.option_side is OptionSide.CE else OptionSide.CE)
    reservations = RedBarV2CanonicalReservationService(SQLiteCanonicalReservationRepository(path), enabled=True)
    service = ReplayGuardedCanonicalPaperService(
        database_path=path,
        repository=StrictSQLiteCanonicalPaperExecutionRepository(path),
        reservation_service=reservations,
        selector=FixedSelector(wrong),
        adapter=FakePaperAdapter(),
        enabled=True,
        mode="PAPER_CANARY",
    )
    assert service.execute(bundle_id=bundle.bundle_id, spot_price=25000.0, requested_at=bundle.created_at).outcome is PaperExecutionOutcome.INVALID_REQUEST
    with sqlite3.connect(path) as conn:
        assert conn.execute("SELECT COUNT(*) FROM canonical_red_bar_v2_bundle_reservations WHERE state='RESERVED'").fetchone()[0] == 0

    path2 = tmp_path / "uncertain.db"
    bundle2, service2, adapter2, _ = _service(path2, adapter=FakePaperAdapter(uncertain=True))
    uncertain = service2.execute(bundle_id=bundle2.bundle_id, spot_price=25000.0, requested_at=bundle2.created_at)
    assert uncertain.outcome is PaperExecutionOutcome.SUBMISSION_UNCERTAIN
    assert uncertain.state is PaperExecutionState.SUBMISSION_UNCERTAIN
    assert adapter2.submissions == 1
    with sqlite3.connect(path2) as conn:
        assert conn.execute("SELECT COUNT(*) FROM canonical_red_bar_v2_bundle_reservations WHERE state='RESERVED'").fetchone()[0] == 1


def test_observability_distinguishes_no_data_corruption_and_available(tmp_path: Path):
    assert SQLiteCanonicalPaperExecutionObservabilityRepository(tmp_path / "missing.db").latest_for_bundle(bundle_id="B").status == "EXECUTION_DATABASE_UNAVAILABLE"
    path = tmp_path / "db.sqlite"
    bundle, service, _, _ = _service(path)
    observer = SQLiteCanonicalPaperExecutionObservabilityRepository(path)
    assert observer.latest_for_bundle(bundle_id=bundle.bundle_id).status == "NO_CANONICAL_EXECUTION"
    result = service.execute(bundle_id=bundle.bundle_id, spot_price=25000.0, requested_at=bundle.created_at)
    assert observer.latest_for_bundle(bundle_id=bundle.bundle_id).status == "EXECUTION_DATA_AVAILABLE"
    with sqlite3.connect(path) as conn:
        conn.execute("UPDATE canonical_red_bar_v2_paper_commands SET payload_sha256='bad' WHERE execution_id=?", (result.command.execution_id,))
    corrupt = observer.latest_for_bundle(bundle_id=bundle.bundle_id)
    assert corrupt.status == "EXECUTION_DATA_CORRUPT"
    assert corrupt.evidence is None
