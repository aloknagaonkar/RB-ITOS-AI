
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from market_lab.paper_production_storage_v1 import (
    MAX_HOLDING_MINUTES,
    MAX_OPEN_POSITIONS,
    LIVE_TRADING_ENABLED,
    PaperEntryRequest,
    PaperPosition,
    PaperSignal,
    close_position,
    confirm_signal_and_open_position,
    count_open_positions,
    ensure_paper_schema,
    get_or_create_waiting_signal,
    get_paper_control,
    list_open_positions,
    paper_detail_view,
    paper_quick_view,
    set_paper_enabled,
    update_position_mark,
)


def engine_for(tmp_path):
    db = tmp_path / "paper.db"
    engine = create_engine(
        f"sqlite:///{db}",
        connect_args={"check_same_thread": False},
    )
    ensure_paper_schema(engine)
    return engine


def waiting(session, idx=1, direction="BULLISH"):
    return get_or_create_waiting_signal(
        session,
        strategy_version="1.0.0",
        session_date="2026-09-16",
        direction=direction,
        option_type="CE" if direction == "BULLISH" else "PE",
        p1_observation_id=100 + idx,
        p1_time=f"2026-09-16T10:{idx:02d}:00+05:30",
        evidence={"p1": True, "vwap_aligned": True},
    )


def entry_request(signal_id, idx=1):
    return PaperEntryRequest(
        waiting_signal_id=signal_id,
        p2_observation_id=200 + idx,
        p2_time=f"2026-09-16T10:{idx+5:02d}:00+05:30",
        instrument_key=f"NSE_FO|TEST{idx}",
        expiry="2026-09-22",
        strike=25000 + idx * 50,
        quantity=65,
        entry_price=100 + idx,
        entry_quote_timestamp=f"2026-09-16T10:{idx+5:02d}:00+05:30",
        evidence_update={"p2": True, "exact_atm": True},
    )


def test_defaults_are_paper_disabled_and_live_impossible(tmp_path):
    engine = engine_for(tmp_path)
    with Session(engine) as session:
        control = get_paper_control(session)
    assert control["enabled"] is False
    assert control["live_enabled"] is False
    assert control["max_open_positions"] == 4
    assert MAX_OPEN_POSITIONS == 4
    assert MAX_HOLDING_MINUTES is None
    assert LIVE_TRADING_ENABLED is False


def test_waiting_signal_is_idempotent(tmp_path):
    engine = engine_for(tmp_path)
    with Session(engine) as session, session.begin():
        one = waiting(session, 1)
        two = waiting(session, 1)
        assert one.id == two.id
        assert session.query(PaperSignal).count() == 1


def test_disabled_paper_rejects_entry(tmp_path):
    engine = engine_for(tmp_path)
    with Session(engine) as session, session.begin():
        signal = waiting(session, 1)
        signal_id = signal.id
    result = confirm_signal_and_open_position(engine, entry_request(signal_id, 1))
    assert result.accepted is False
    assert result.reason_code == "PAPER_DISABLED"
    with Session(engine) as session:
        assert count_open_positions(session) == 0


def test_four_positions_persist_and_fifth_is_rejected(tmp_path, monkeypatch):
    engine = engine_for(tmp_path)
    monkeypatch.setattr(
        "market_lab.paper_production_storage_v1.PAPER_EXECUTOR_LOCK",
        tmp_path / "executor.lock",
    )
    set_paper_enabled(engine, True)

    signal_ids = []
    with Session(engine) as session, session.begin():
        for i in range(1, 6):
            signal_ids.append(waiting(session, i).id)

    for i in range(1, 5):
        result = confirm_signal_and_open_position(engine, entry_request(signal_ids[i-1], i))
        assert result.accepted is True
        assert result.open_positions == i

    fifth = confirm_signal_and_open_position(engine, entry_request(signal_ids[4], 5))
    assert fifth.accepted is False
    assert fifth.reason_code == "MAX_OPEN_POSITIONS"

    with Session(engine) as session:
        assert count_open_positions(session) == 4
        assert len(list_open_positions(session)) == 4


def test_replaying_confirmed_signal_does_not_duplicate_position(tmp_path, monkeypatch):
    engine = engine_for(tmp_path)
    monkeypatch.setattr(
        "market_lab.paper_production_storage_v1.PAPER_EXECUTOR_LOCK",
        tmp_path / "executor.lock",
    )
    set_paper_enabled(engine, True)
    with Session(engine) as session, session.begin():
        signal_id = waiting(session, 1).id

    request = entry_request(signal_id, 1)
    first = confirm_signal_and_open_position(engine, request)
    second = confirm_signal_and_open_position(engine, request)

    assert first.accepted is True
    assert second.status == "IDEMPOTENT_REPLAY"
    assert first.position_id == second.position_id

    with Session(engine) as session:
        assert count_open_positions(session) == 1


def test_position_risk_state_is_independent_and_has_no_time_exit(tmp_path, monkeypatch):
    engine = engine_for(tmp_path)
    monkeypatch.setattr(
        "market_lab.paper_production_storage_v1.PAPER_EXECUTOR_LOCK",
        tmp_path / "executor.lock",
    )
    set_paper_enabled(engine, True)
    with Session(engine) as session, session.begin():
        signal_id = waiting(session, 1).id

    opened = confirm_signal_and_open_position(engine, entry_request(signal_id, 1))

    with Session(engine) as session, session.begin():
        p = session.get(PaperPosition, opened.position_id)
        assert update_position_mark(
            session, p, bid=p.entry_price * 1.06, ltp=None, quote_time="2026-09-16T10:30:00+05:30"
        ) == "HOLD"
        assert p.breakeven_active is True
        assert p.trailing_active is False

    with Session(engine) as session, session.begin():
        p = session.get(PaperPosition, opened.position_id)
        assert update_position_mark(
            session, p, bid=p.entry_price * 1.12, ltp=None, quote_time="2026-09-16T14:30:00+05:30"
        ) == "HOLD"
        assert p.trailing_active is True
        assert p.status == "OPEN"


def test_restart_recovery_reads_persisted_open_positions(tmp_path, monkeypatch):
    engine = engine_for(tmp_path)
    monkeypatch.setattr(
        "market_lab.paper_production_storage_v1.PAPER_EXECUTOR_LOCK",
        tmp_path / "executor.lock",
    )
    set_paper_enabled(engine, True)
    with Session(engine) as session, session.begin():
        signal_id = waiting(session, 1).id
    opened = confirm_signal_and_open_position(engine, entry_request(signal_id, 1))

    # New SQLAlchemy session = process-style reload of authoritative DB state.
    with Session(engine) as new_session:
        positions = list_open_positions(new_session)
        assert len(positions) == 1
        assert positions[0].id == opened.position_id
        assert positions[0].current_stop == pytest.approx(positions[0].entry_price * 0.95)


def test_close_position_frees_capacity_and_uses_bid_side(tmp_path, monkeypatch):
    engine = engine_for(tmp_path)
    monkeypatch.setattr(
        "market_lab.paper_production_storage_v1.PAPER_EXECUTOR_LOCK",
        tmp_path / "executor.lock",
    )
    set_paper_enabled(engine, True)
    with Session(engine) as session, session.begin():
        signal_id = waiting(session, 1).id
    opened = confirm_signal_and_open_position(engine, entry_request(signal_id, 1))

    with Session(engine) as session, session.begin():
        p = session.get(PaperPosition, opened.position_id)
        close_position(
            session,
            p,
            exit_price=p.entry_price * 0.97,
            exit_time="2026-09-16T11:00:00+05:30",
            exit_reason="MANUAL_TEST_CLOSE",
            fill_basis="BID",
        )

    with Session(engine) as session:
        assert count_open_positions(session) == 0
        p = session.get(PaperPosition, opened.position_id)
        assert p.status == "CLOSED"
        assert p.exit_fill_basis == "BID"


def test_quick_and_detail_views_are_db_derived(tmp_path):
    engine = engine_for(tmp_path)
    with Session(engine) as session, session.begin():
        waiting(session, 1)

    with Session(engine) as session:
        quick = paper_quick_view(session)
        detail = paper_detail_view(session)
        assert quick["capacity"] == 4
        assert quick["control"]["live_enabled"] is False
        assert len(detail["signals"]) == 1
        assert detail["signals"][0]["status"] == "WAIT_P2"
