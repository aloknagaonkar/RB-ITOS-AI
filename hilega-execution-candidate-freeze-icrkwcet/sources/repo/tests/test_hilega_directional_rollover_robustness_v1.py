from datetime import date, datetime
from zoneinfo import ZoneInfo

from market_lab.hilega_directional_live_shadow_v1 import (
    HilegaDirectionalLiveShadowCoordinatorV1,
)


IST = ZoneInfo("Asia/Kolkata")

D1 = date(2026, 9, 24)
D2 = date(2026, 9, 25)
D3 = date(2026, 9, 26)


class RolloverSources:
    def __init__(self):
        self.nifty_calls = 0
        self.contract_calls = 0
        self.option_calls = 0

    def warmup_candles(
        self,
        session_date,
        cache_root,
    ):
        return []

    def nifty_intraday_1m(
        self,
        *,
        now=None,
    ):
        self.nifty_calls += 1
        return []

    def option_contracts(
        self,
        *args,
        **kwargs,
    ):
        self.contract_calls += 1
        raise AssertionError(
            "rollover bootstrap must not rebuild old option identity"
        )

    def option_intraday_1m(
        self,
        instrument_key,
    ):
        self.option_calls += 1
        raise AssertionError(
            "no stale option lifecycle should survive rollover"
        )


def coordinator(tmp_path):
    return HilegaDirectionalLiveShadowCoordinatorV1(
        market_sources=RolloverSources(),
        option_expiry=date(2026, 9, 29),
        step_audit_path=tmp_path / "audit.jsonl",
        health_path=tmp_path / "health.jsonl",
        cache_root=tmp_path / "cache",
        warmup_calendar_days=0,
    )


def append_old_option_record(
    c,
    *,
    day,
    direction,
    status,
):
    signal_bar = datetime(
        day.year,
        day.month,
        day.day,
        12,
        40,
        tzinfo=IST,
    )

    c._audit(
        signal_bar,
        f"{direction}_OPTION_SHADOW_START",
        "PASS",
        {
            "status": status,
            "signal_bar": signal_bar.isoformat(),
            # Deliberately incomplete identity. It must never even be
            # considered when bootstrapping another session.
            "shadow_selected_instrument_keys": [
                "STALE|-2",
                "STALE|-1",
                "STALE|0",
                "STALE|1",
                "STALE|2",
            ],
        },
        checkpoint=signal_bar,
    )


def test_new_session_bootstrap_resets_all_runtime_lifecycle_state(
    tmp_path,
):
    c = coordinator(tmp_path)

    old_ce = c.ce_shadow
    old_pe = c.pe_shadow

    # Simulate state left in memory from the prior trading session.
    c._bootstrapped_date = D1

    c._pending_ce_exits["OLD_CE_EXIT"] = object()
    c._pending_pe_exits["OLD_PE_EXIT"] = object()

    c._pending_ce_entries["OLD_CE_ENTRY"] = object()
    c._pending_pe_entries["OLD_PE_ENTRY"] = object()

    c._pending_ce_entry_exits["OLD_CE_ENTRY"] = object()
    c._pending_pe_entry_exits["OLD_PE_ENTRY"] = object()

    c._ce_last_update = datetime(
        2026, 9, 24, 14, 30, tzinfo=IST
    )
    c._pe_last_update = datetime(
        2026, 9, 24, 14, 31, tzinfo=IST
    )
    c._last_bar_ts = datetime(
        2026, 9, 24, 14, 50, tzinfo=IST
    )
    c._cutoff_done_date = D1

    # An unresolved prior-session audit record must not be restored.
    append_old_option_record(
        c,
        day=D1,
        direction="BULLISH",
        status="ACTIVE",
    )

    result = c.bootstrap(
        datetime(
            2026,
            9,
            25,
            10,
            0,
            tzinfo=IST,
        )
    )

    assert result["status"] == "BOOTSTRAPPED"
    assert result["session_date"] == D2.isoformat()

    # Fresh lifecycle objects.
    assert c.ce_shadow is not old_ce
    assert c.pe_shadow is not old_pe

    assert c.ce_shadow.snapshot is None
    assert c.pe_shadow.snapshot is None

    # All stale pending state is gone.
    assert c._pending_ce_exits == {}
    assert c._pending_pe_exits == {}

    assert c._pending_ce_entries == {}
    assert c._pending_pe_entries == {}

    assert c._pending_ce_entry_exits == {}
    assert c._pending_pe_entry_exits == {}

    # All rollover-sensitive timestamps are reset.
    assert c._ce_last_update is None
    assert c._pe_last_update is None
    assert c._last_bar_ts is None
    assert c._cutoff_done_date is None

    assert c._bootstrapped_date == D2

    # Prior-day unresolved audit must not restore.
    restore = result["option_restore"]

    assert restore["restored_active_count"] == 0
    assert restore["restored_pending_exit_count"] == 0
    assert restore["blocked_restore_count"] == 0
    assert restore["restored_instrument_keys"] == []

    # Absolutely no contract-master or stale option-minute lookup.
    assert c.sources.contract_calls == 0
    assert c.sources.option_calls == 0

    assert c.step_audit.verify_chain() == (True, None)


def test_same_session_bootstrap_is_idempotent_and_does_not_reset_state(
    tmp_path,
):
    c = coordinator(tmp_path)

    now = datetime(
        2026,
        9,
        25,
        10,
        0,
        tzinfo=IST,
    )

    first = c.bootstrap(now)

    assert first["status"] == "BOOTSTRAPPED"

    audit_count = len(
        c.step_audit.read_all()
    )
    nifty_calls = c.sources.nifty_calls

    # Marker represents valid current-session in-memory state.
    marker = object()
    c._pending_ce_exits["CURRENT"] = marker

    second = c.bootstrap(now)

    assert second == {
        "status": "ALREADY_BOOTSTRAPPED",
        "session_date": D2.isoformat(),
    }

    # Same-day bootstrap must not clear/reconstruct current runtime state.
    assert c._pending_ce_exits["CURRENT"] is marker

    # No additional acquisition or audit side effects.
    assert c.sources.nifty_calls == nifty_calls
    assert len(c.step_audit.read_all()) == audit_count

    assert c.sources.contract_calls == 0
    assert c.sources.option_calls == 0

    assert c.step_audit.verify_chain() == (True, None)


def test_repeated_session_rollovers_do_not_accumulate_stale_option_state(
    tmp_path,
):
    c = coordinator(tmp_path)

    # Session 1.
    r1 = c.bootstrap(
        datetime(
            2026,
            9,
            24,
            10,
            0,
            tzinfo=IST,
        )
    )

    assert r1["status"] == "BOOTSTRAPPED"

    # Leave unresolved D1 state in audit + memory.
    append_old_option_record(
        c,
        day=D1,
        direction="BEARISH",
        status="PENDING_EXACT_EXIT",
    )

    c._pending_pe_exits["D1"] = object()
    c._pending_pe_entries["D1"] = object()
    c._pending_pe_entry_exits["D1"] = object()

    # Session 2 must not inherit D1.
    r2 = c.bootstrap(
        datetime(
            2026,
            9,
            25,
            10,
            0,
            tzinfo=IST,
        )
    )

    assert r2["status"] == "BOOTSTRAPPED"

    assert r2["option_restore"][
        "restored_active_count"
    ] == 0

    assert r2["option_restore"][
        "restored_pending_exit_count"
    ] == 0

    assert c._pending_pe_exits == {}
    assert c._pending_pe_entries == {}
    assert c._pending_pe_entry_exits == {}

    # Now leave D2 stale state as well.
    append_old_option_record(
        c,
        day=D2,
        direction="BULLISH",
        status="ACTIVE",
    )

    c._pending_ce_exits["D2"] = object()
    c._pending_ce_entries["D2"] = object()
    c._pending_ce_entry_exits["D2"] = object()

    # Session 3 must inherit neither D1 nor D2.
    r3 = c.bootstrap(
        datetime(
            2026,
            9,
            26,
            10,
            0,
            tzinfo=IST,
        )
    )

    assert r3["status"] == "BOOTSTRAPPED"

    restore = r3["option_restore"]

    assert restore["restored_active_count"] == 0
    assert restore["restored_pending_exit_count"] == 0
    assert restore["blocked_restore_count"] == 0
    assert restore["restored_instrument_keys"] == []

    assert c._pending_ce_exits == {}
    assert c._pending_pe_exits == {}

    assert c._pending_ce_entries == {}
    assert c._pending_pe_entries == {}

    assert c._pending_ce_entry_exits == {}
    assert c._pending_pe_entry_exits == {}

    assert c.sources.contract_calls == 0
    assert c.sources.option_calls == 0

    assert c.step_audit.verify_chain() == (True, None)
