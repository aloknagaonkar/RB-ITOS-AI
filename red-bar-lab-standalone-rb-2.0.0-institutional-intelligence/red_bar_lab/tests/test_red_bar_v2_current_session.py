from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pandas as pd

from red_bar_lab.domain.red_bar_v2 import ExitReason, RiskPlanRejection
from red_bar_lab.operations.red_bar_v2_ui_snapshot import (
    RedBarV2UISnapshot,
    persist_red_bar_v2_ui_snapshot,
    read_red_bar_v2_ui_snapshot,
)
from red_bar_lab.services import red_bar_v2_current_session as module
from red_bar_lab.services.red_bar_v2_derived_exit_store import (
    persist_red_bar_v2_derived_exit,
    read_red_bar_v2_derived_exits,
)
from red_bar_lab.services.red_bar_v2_derived_exits import DerivedExit, OPEN_AT_END


class _Database:
    def read_paper_execution_orders(self, account_id):
        assert account_id == "PAPER-STD"
        return [
            {
                "execution_strategy_source": "RED_BAR_V2",
                "exit_timestamp": "2026-08-19T09:45:00+05:30",
            },
            {
                "execution_strategy_source": "REFERENCE_LEVEL",
                "exit_timestamp": "2026-08-19T10:00:00+05:30",
            },
        ]


class _Upstox:
    def intraday_candles(self, instrument_key, interval_minutes=1):
        assert interval_minutes == 1
        return pd.DataFrame(
            {"open": [1.0], "high": [1.0], "low": [1.0], "close": [1.0], "volume": [1.0]},
            index=pd.DatetimeIndex(["2026-08-19T09:20:00+05:30"]),
        )


def test_current_session_blocks_without_futures_key(tmp_path, monkeypatch):
    monkeypatch.delenv("NIFTY_FUTURES_INSTRUMENT_KEY", raising=False)
    result = module.evaluate_current_session_red_bar_v2(
        upstox=_Upstox(),
        database=_Database(),
        settings=SimpleNamespace(artifacts_root=tmp_path),
        instrument_key="NSE_INDEX|Nifty 50",
    )
    assert result.status == "BLOCKED"
    assert result.reason == "NIFTY_FUTURES_INSTRUMENT_KEY_UNAVAILABLE"


def test_current_session_refreshes_snapshot_for_paper(tmp_path, monkeypatch):
    monkeypatch.delenv("NIFTY_FUTURES_INSTRUMENT_KEY", raising=False)
    persist_red_bar_v2_ui_snapshot(
        RedBarV2UISnapshot(
            futures_instrument_key="NSE_FO|12345",
            futures_symbol="NIFTY26AUGFUT",
            futures_expiry="2026-08-27",
        ),
        artifacts_root=tmp_path,
    )
    captured = {}

    def fake_run(index_candles, futures_candles, **kwargs):
        captured.update(kwargs)
        persist_red_bar_v2_ui_snapshot(
            RedBarV2UISnapshot(
                alignment_status="READY",
                admission_allowed=True,
                direction="BULLISH",
                option_side="CE",
                last_evaluation_timestamp="2026-08-19T09:20:00+05:30",
                futures_instrument_key=kwargs["vwap_instrument_key"],
            ),
            artifacts_root=kwargs["artifacts_root"],
        )
        return SimpleNamespace(
            health=SimpleNamespace(status="READY", reason="FULL_TIMESTAMP_ALIGNMENT"),
            replay=SimpleNamespace(admitted_candidates=1, closed_trades=1, events=()),
        )

    monkeypatch.setattr(module, "run_monitored_red_bar_v2_futures_replay", fake_run)
    result = module.evaluate_current_session_red_bar_v2(
        upstox=_Upstox(),
        database=_Database(),
        settings=SimpleNamespace(artifacts_root=tmp_path),
        instrument_key="NSE_INDEX|Nifty 50",
    )

    assert result.status == "READY"
    assert result.admitted_candidates == 1
    assert captured["exit_timestamps"] == ["2026-08-19T09:45:00+05:30"]
    snapshot = read_red_bar_v2_ui_snapshot(tmp_path)
    assert snapshot is not None
    assert snapshot.mode == "PAPER"
    assert snapshot.execution_scope == "PAPER_TRADING_ONLY"


def _allowed_event():
    return SimpleNamespace(
        timestamp=datetime.fromisoformat("2026-08-20T12:41:00+05:30"),
        event_type="CANDIDATE_ADMISSION",
        candidate_allowed=True,
        direction="BULLISH",
        option_side="CE",
        admission_code="FULL_DIRECTIONAL_ALIGNMENT",
        details={
            "trend_strength": "CONFIRMED",
            "admission_reason": "Fresh confirmed bullish candidate.",
            "conditions": {"midpoint_aligned": True},
        },
    )


def test_live_session_restores_candidate_when_only_replay_trade_blocks():
    blocked = RedBarV2UISnapshot(
        alignment_status="READY",
        directional_state="CONFIRMED_BULLISH",
        direction="BULLISH",
        option_side="CE",
        trade_status="ACTIVE",
        trade_id="RBV2-FVWAP-0001",
        admission_allowed=False,
        admission_code="ACTIVE_TRADE_BLOCK",
        admission_reason="Synthetic replay trade remains active.",
        last_evaluation_timestamp="2026-08-20T13:00:00+05:30",
        index_timestamp="2026-08-20T12:59:00+05:30",
        futures_timestamp="2026-08-20T12:59:00+05:30",
    )
    monitored = SimpleNamespace(replay=SimpleNamespace(events=(_allowed_event(),)))

    restored = module._restore_live_candidate_when_replay_only_blocked(
        blocked,
        monitored,
        active_v2_order_exists=False,
    )

    assert restored.admission_allowed is True
    assert restored.admission_timestamp == "2026-08-20T12:41:00+05:30"
    assert restored.admission_code == "FULL_DIRECTIONAL_ALIGNMENT"
    assert restored.direction == "BULLISH"
    assert restored.option_side == "CE"
    assert restored.trade_status == "FLAT"
    assert restored.trade_id is None
    assert restored.last_evaluation_timestamp == "2026-08-20T13:00:00+05:30"
    assert restored.index_timestamp == "2026-08-20T12:59:00+05:30"
    assert restored.futures_timestamp == "2026-08-20T12:59:00+05:30"


def test_live_session_preserves_block_when_real_v2_order_is_active():
    blocked = RedBarV2UISnapshot(
        admission_allowed=False,
        admission_code="ACTIVE_TRADE_BLOCK",
        trade_status="ACTIVE",
        trade_id="PAPER-ACTIVE",
    )
    monitored = SimpleNamespace(replay=SimpleNamespace(events=(_allowed_event(),)))

    result = module._restore_live_candidate_when_replay_only_blocked(
        blocked,
        monitored,
        active_v2_order_exists=True,
    )

    assert result is blocked
    assert result.admission_allowed is False
    assert result.admission_code == "ACTIVE_TRADE_BLOCK"


# --- Derived exits: how an observational session retires its own trade row ----
#
# The replay's one route from ACTIVE to CLOSED is the exits it is handed, and
# observational mode places no orders -- so it has no exits, its first trade row
# never comes off, every later candidate is refused ACTIVE_TRADE_BLOCK, and the
# displayed direction stays frozen on whatever was admitted first. That is what
# the live session did for 103 consecutive cycles while price sat eighteen points
# the other side of the midpoint that justified the direction. Handing the
# policy's own exits back through the same parameter is what unfreezes it.

IST = timezone(timedelta(hours=5, minutes=30))
SESSION_DATE = "2026-08-19"
UNDERLYING = "NSE_INDEX|Nifty 50"
ORDER_EXIT = "2026-08-19T09:45:00+05:30"
ENTRY = datetime(2026, 8, 19, 9, 25, tzinfo=IST)
FED_AT = datetime(2026, 8, 19, 10, 22, tzinfo=IST)


def _policy_exit(**overrides) -> DerivedExit:
    """A settled exit in the shape the resolver hands one over.

    Only the fields this wiring reads are filled in -- the entry it settles, the
    moment to feed, and enough of an outcome to audit. Full round-trip fidelity of
    plans and outcomes is the store's own test.
    """
    fields = {
        "entry_timestamp": ENTRY,
        "trade_id": "RBV2-FVWAP-0001",
        "direction": "BEARISH",
        "plan": None,
        "rejection": None,
        "outcome": SimpleNamespace(exit_reason=ExitReason.STRUCTURE, r_multiple=-0.24),
        "exit_timestamp": FED_AT - timedelta(minutes=1),
        "fed_at": FED_AT,
    }
    return DerivedExit(**{**fields, **overrides})


def _settings(tmp_path: Path, *, with_database: bool = True) -> SimpleNamespace:
    fields = {"artifacts_root": tmp_path}
    if with_database:
        fields["database_path"] = tmp_path / "rb.db"
    return SimpleNamespace(**fields)


def _run(tmp_path, monkeypatch, *, settings=None, resolver=None) -> tuple:
    """One cycle, with the replay faked and the resolver optionally faked too.

    Returns the result and the kwargs the replay was called with, which is where
    ``exit_timestamps`` -- the thing under test -- actually shows up.
    """
    monkeypatch.delenv("NIFTY_FUTURES_INSTRUMENT_KEY", raising=False)
    if read_red_bar_v2_ui_snapshot(tmp_path) is None:
        persist_red_bar_v2_ui_snapshot(
            RedBarV2UISnapshot(futures_instrument_key="NSE_FO|12345"),
            artifacts_root=tmp_path,
        )
    captured: dict = {}

    def fake_run(index_candles, futures_candles, **kwargs):
        captured.update(kwargs)
        return SimpleNamespace(
            health=SimpleNamespace(status="READY", reason="FULL_TIMESTAMP_ALIGNMENT"),
            replay=SimpleNamespace(admitted_candidates=1, closed_trades=0, events=()),
        )

    monkeypatch.setattr(module, "run_monitored_red_bar_v2_futures_replay", fake_run)
    if resolver is not None:
        monkeypatch.setattr(module, "resolve_next_derived_exit", resolver)
    result = module.evaluate_current_session_red_bar_v2(
        upstox=_Upstox(),
        database=_Database(),
        settings=settings if settings is not None else _settings(tmp_path),
        instrument_key=UNDERLYING,
    )
    return result, captured


def test_an_exit_the_policy_settled_is_recorded_and_handed_back_next_cycle(
    tmp_path, monkeypatch
):
    """The fix, end to end: one cycle resolves it, the next cycle acts on it.

    A cycle cannot use what it just resolved -- its own replay has already run, and
    re-running it would write the artifacts twice. So the exit is written down and
    the next cycle feeds it in. Two cycles is the whole convergence step, and the
    ~32-second gap between them is the cost.
    """
    settings = _settings(tmp_path)
    calls: list[dict] = []

    def resolver(replay, index_candles, futures_candles, **kwargs):
        calls.append({"replay": replay, **kwargs})
        if ENTRY.isoformat() in [str(stamp) for stamp in kwargs["resolved_entries"]]:
            return None  # already settled; this is the steady state
        return _policy_exit()

    first, first_replay = _run(
        tmp_path, monkeypatch, settings=settings, resolver=resolver
    )

    # Nothing to hand over on the cycle that discovers it.
    assert first_replay["exit_timestamps"] == [ORDER_EXIT]
    assert calls[0]["resolved_entries"] == []
    assert calls[0]["replay"].admitted_candidates == 1
    (recorded,) = read_red_bar_v2_derived_exits(
        settings.database_path, trading_date=SESSION_DATE, instrument_key=UNDERLYING
    )
    assert recorded["fed_at"] == FED_AT.isoformat()
    assert recorded["exit_reason"] == ExitReason.STRUCTURE.value
    assert [row["fed_at"] for row in first.derived_exits] == [FED_AT.isoformat()]

    second, second_replay = _run(
        tmp_path, monkeypatch, settings=settings, resolver=resolver
    )

    # The row the replay needed in order to close the position it opened.
    assert second_replay["exit_timestamps"] == [ORDER_EXIT, FED_AT.isoformat()]
    assert calls[1]["resolved_entries"] == [ENTRY.isoformat()]
    assert len(second.derived_exits) == 1, "settled once, not once per cycle"


def test_a_position_still_open_on_the_candles_so_far_is_not_recorded(
    tmp_path, monkeypatch
):
    """On a live session the last candle is the last one *so far*.

    Research reads a walk that reaches the end of the frame as "held to the
    close", because the day is over. A cycle at 10:30 cannot: the position is
    simply not closed yet, and writing that verdict would freeze a decision the
    next candle can still overturn. So it is offered and declined, and the next
    cycle asks again.
    """
    settings = _settings(tmp_path)
    still_open = _policy_exit(
        outcome=None, exit_timestamp=None, fed_at=None, status=OPEN_AT_END
    )

    result, replay_kwargs = _run(
        tmp_path,
        monkeypatch,
        settings=settings,
        resolver=lambda *args, **kwargs: still_open,
    )

    assert result.derived_exits == ()
    assert replay_kwargs["exit_timestamps"] == [ORDER_EXIT]
    assert (
        read_red_bar_v2_derived_exits(
            settings.database_path,
            trading_date=SESSION_DATE,
            instrument_key=UNDERLYING,
        )
        == []
    )


def test_an_unplannable_entry_is_still_retired_so_the_session_continues(
    tmp_path, monkeypatch
):
    """No plan is not the same as no row: the replay opened one, and it blocks.

    Risk outside the band leaves the entry unsized, but the trade row exists and
    refuses everything behind it until it closes. Its exit is its own entry bar,
    and the rejection is what keeps it out of the day's trade count.
    """
    settings = _settings(tmp_path)
    unplannable = _policy_exit(
        outcome=None,
        exit_timestamp=None,
        fed_at=ENTRY + timedelta(minutes=1),
        rejection=RiskPlanRejection.RISK_BELOW_FLOOR.value,
    )

    result, _replay_kwargs = _run(
        tmp_path,
        monkeypatch,
        settings=settings,
        resolver=lambda *args, **kwargs: unplannable,
    )

    (row,) = result.derived_exits
    assert row["rejection"] == RiskPlanRejection.RISK_BELOW_FLOOR.value
    assert row["exit_reason"] is None
    assert row["fed_at"] == (ENTRY + timedelta(minutes=1)).isoformat()


def test_a_caller_with_no_database_derives_nothing_at_all(tmp_path, monkeypatch):
    """No file to carry an exit in means the whole mechanism is skipped.

    An exit that cannot outlive its own cycle is one the next cycle derives again
    and discards again, forever. Rather than pay for that, a caller that has
    nowhere to record one is left exactly as it was -- which is also what keeps the
    live order-book seam the only source of exits for anyone who wants it that way.
    """
    def resolver(*_args, **_kwargs):
        raise AssertionError("nothing to resolve for: there is nowhere to record it")

    result, replay_kwargs = _run(
        tmp_path,
        monkeypatch,
        settings=_settings(tmp_path, with_database=False),
        resolver=resolver,
    )

    assert result.derived_exits == ()
    assert replay_kwargs["exit_timestamps"] == [ORDER_EXIT]


def test_the_store_is_found_on_the_database_the_cycle_already_writes_to(
    tmp_path, monkeypatch
):
    """Live hands over a ``RedBarDatabase``, and its own path is the right file.

    The exits belong beside the cycle evaluations, in the database the monitor
    already opened -- not in a second file that only this feature knows about.
    """
    class _DatabaseWithPath(_Database):
        path = tmp_path / "rb.db"

    monkeypatch.delenv("NIFTY_FUTURES_INSTRUMENT_KEY", raising=False)
    persist_red_bar_v2_ui_snapshot(
        RedBarV2UISnapshot(futures_instrument_key="NSE_FO|12345"),
        artifacts_root=tmp_path,
    )
    monkeypatch.setattr(
        module,
        "run_monitored_red_bar_v2_futures_replay",
        lambda *args, **kwargs: SimpleNamespace(
            health=SimpleNamespace(status="READY", reason="FULL_TIMESTAMP_ALIGNMENT"),
            replay=SimpleNamespace(admitted_candidates=1, closed_trades=0, events=()),
        ),
    )
    monkeypatch.setattr(
        module, "resolve_next_derived_exit", lambda *args, **kwargs: _policy_exit()
    )

    result = module.evaluate_current_session_red_bar_v2(
        upstox=_Upstox(),
        database=_DatabaseWithPath(),
        settings=SimpleNamespace(artifacts_root=tmp_path),
        instrument_key=UNDERLYING,
    )

    assert [row["fed_at"] for row in result.derived_exits] == [FED_AT.isoformat()]
    assert read_red_bar_v2_derived_exits(
        tmp_path / "rb.db", trading_date=SESSION_DATE, instrument_key=UNDERLYING
    )


def test_derived_exits_are_scoped_to_the_session_being_evaluated(tmp_path, monkeypatch):
    """Yesterday's exits must not close today's row.

    The store holds every day the instrument has traded. An exit read from another
    session would retire a trade row this one never opened, and the replay consumes
    whatever it is handed without asking which day it came from.
    """
    settings = _settings(tmp_path)
    for trading_date in (SESSION_DATE, "2026-08-18"):
        persist_red_bar_v2_derived_exit(
            settings.database_path,
            trading_date=trading_date,
            instrument_key=UNDERLYING,
            exit=_policy_exit(),
        )
    persist_red_bar_v2_derived_exit(
        settings.database_path,
        trading_date=SESSION_DATE,
        instrument_key="NSE_INDEX|Bank Nifty",
        exit=_policy_exit(),
    )

    _result, replay_kwargs = _run(
        tmp_path,
        monkeypatch,
        settings=settings,
        resolver=lambda *args, **kwargs: None,
    )

    assert replay_kwargs["exit_timestamps"] == [ORDER_EXIT, FED_AT.isoformat()]


def test_the_trading_date_is_the_sessions_first_candle(tmp_path):
    """The key the exits are filed under has to be stable across a day's cycles.

    It is the replay's own rule -- the earliest candle's date -- so a row written at
    09:26 is still found at 15:14 however much the intraday window has grown.
    """
    stamps = pd.DatetimeIndex(
        ["2026-08-19T09:20:00+05:30", "2026-08-19T15:14:00+05:30"]
    )
    frame = pd.DataFrame({"close": [1.0, 2.0]}, index=stamps)

    assert module._session_trading_date(frame) == SESSION_DATE
    assert module._session_trading_date(frame.iloc[:1]) == SESSION_DATE
    assert (
        module._session_trading_date(
            pd.DataFrame({"timestamp": list(reversed(stamps)), "close": [2.0, 1.0]})
        )
        == SESSION_DATE
    )
    assert module._session_trading_date(pd.DataFrame({"close": []})) is None
