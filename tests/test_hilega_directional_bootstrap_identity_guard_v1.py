from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo
import inspect

from market_lab.hilega_directional_live_shadow_v1 import (
    HilegaDirectionalLiveShadowCoordinatorV1,
)
from market_lab.hilega_milega_option_shadow_lifecycle_v1 import (
    HilegaMilegaOptionShadowLifecycleV1,
    SELECTION_POLICY as CE_SELECTION_POLICY,
)
from market_lab.hilega_milega_pe_option_shadow_lifecycle_v1 import (
    HilegaMilegaPEOptionShadowLifecycleV1,
    SELECTION_POLICY as PE_SELECTION_POLICY,
)
from market_lab.live_shadow_step_audit_v1 import (
    ShadowStepAuditStoreV1,
)


IST = ZoneInfo("Asia/Kolkata")


def _leg(
    relation,
    strike,
    side,
    key,
    entry,
):
    return {
        "strike": strike,
        "side": side,
        "instrument_key": key,
        "relation_to_atm": relation,
        "expiry": "2026-09-29",
        "entry_timestamp": (
            "2026-09-25T12:45:00+05:30"
        ),
        "entry_open": entry,
        "latest_completed_minute": (
            "2026-09-25T12:49:00+05:30"
        ),
        "latest_close": entry + 1.0,
        "current_points": 1.0,
        "current_return_pct": 1.0,
        "mfe_points": 2.0,
        "mfe_pct": 2.0,
        "mae_points": -1.0,
        "mae_pct": -1.0,
        "exit_timestamp": None,
        "exit_open": None,
        "realized_points": None,
        "realized_return_pct": None,
    }


def _payload(
    *,
    direction,
    status="ACTIVE",
):
    side = (
        "CE"
        if direction == "BULLISH"
        else "PE"
    )

    selection_policy = (
        CE_SELECTION_POLICY
        if direction == "BULLISH"
        else PE_SELECTION_POLICY
    )

    keys = [
        "AUDITED|-2",
        "AUDITED|-1",
        "AUDITED|0",
        "AUDITED|1",
        "AUDITED|2",
    ]

    legs = [
        _leg(
            -2,
            22950.0,
            side,
            keys[0],
            50.0,
        ),
        _leg(
            -1,
            23000.0,
            side,
            keys[1],
            60.0,
        ),
        _leg(
            0,
            23050.0,
            side,
            keys[2],
            70.0,
        ),
        _leg(
            1,
            23100.0,
            side,
            keys[3],
            80.0,
        ),
        _leg(
            2,
            23150.0,
            side,
            keys[4],
            90.0,
        ),
    ]

    if status == "PENDING_EXACT_EXIT":
        for leg in legs:
            leg["latest_completed_minute"] = (
                "2026-09-25T13:09:00+05:30"
            )

    return {
        "model": "TEST",
        "status": status,
        "signal_bar": (
            "2026-09-25T12:40:00+05:30"
        ),
        "signal_boundary": (
            "2026-09-25T12:45:00+05:30"
        ),
        "signal_spot": 23056.75,
        "source": (
            f"{direction}_ROUTE_B_STRUCTURAL"
        ),
        "expiry": "2026-09-29",
        "atm": 23050.0,
        "selection_policy": selection_policy,
        "shadow_selected_instrument_keys": (
            keys
        ),
        "active": status == "ACTIVE",
        "latest_completed_minute": (
            "2026-09-25T12:49:00+05:30"
            if status == "ACTIVE"
            else "2026-09-25T13:09:00+05:30"
        ),
        "exit_reason": (
            None
            if status == "ACTIVE"
            else "STRUCTURAL_EXIT_TEST"
        ),
        "pending_exit_boundary": (
            None
            if status == "ACTIVE"
            else "2026-09-25T13:10:00+05:30"
        ),
        "issue": None,
        "legs": legs,
    }


class DirectionalState:
    def __init__(self, owner):
        self.trade_owner = owner


def _coordinator(
    tmp_path,
    *,
    owner,
):
    coordinator = object.__new__(
        HilegaDirectionalLiveShadowCoordinatorV1
    )

    coordinator.step_audit = (
        ShadowStepAuditStoreV1(
            tmp_path / "step-audit.jsonl"
        )
    )

    coordinator.directional = (
        DirectionalState(owner)
    )

    coordinator.ce_shadow = (
        HilegaMilegaOptionShadowLifecycleV1()
    )

    coordinator.pe_shadow = (
        HilegaMilegaPEOptionShadowLifecycleV1()
    )

    coordinator._pending_ce_exits = {}
    coordinator._pending_pe_exits = {}

    coordinator._pending_ce_entries = {}
    coordinator._pending_pe_entries = {}

    coordinator._pending_ce_entry_exits = {}
    coordinator._pending_pe_entry_exits = {}

    coordinator._ce_last_update = None
    coordinator._pe_last_update = None

    return coordinator


def _append(
    coordinator,
    *,
    direction,
    stage,
    payload,
):
    coordinator.step_audit.append(
        event_time=datetime(
            2026,
            9,
            25,
            13,
            0,
            tzinfo=IST,
        ),
        checkpoint=datetime.fromisoformat(
            payload["signal_bar"]
        ),
        stage=(
            f"{direction}_OPTION_SHADOW_"
            f"{stage}"
        ),
        status="PASS",
        payload=payload,
    )


def test_bootstrap_source_never_replays_option_handle_decision():
    import ast
    import textwrap

    source = inspect.getsource(
        HilegaDirectionalLiveShadowCoordinatorV1.bootstrap
    )

    tree = ast.parse(
        textwrap.dedent(source)
    )

    calls = []

    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue

        fn = node.func

        if isinstance(fn, ast.Attribute):
            calls.append(fn.attr)

        elif isinstance(fn, ast.Name):
            calls.append(fn.id)

    # Bootstrap must reconstruct directional state without executing
    # historical option start/exit side effects.
    assert "_handle_decision" not in calls

    # Frozen audited option identity is restored only after directional replay.
    assert "_restore_audited_option_state" in calls


def test_active_restore_uses_exact_audited_keys(tmp_path):
    coordinator = _coordinator(
        tmp_path,
        owner="BULLISH",
    )

    payload = _payload(
        direction="BULLISH",
        status="ACTIVE",
    )

    _append(
        coordinator,
        direction="BULLISH",
        stage="START",
        payload=payload,
    )

    result = (
        coordinator
        ._restore_audited_option_state(
            now=datetime(
                2026,
                9,
                25,
                13,
                1,
                tzinfo=IST,
            ),
            session_date=date(
                2026,
                9,
                25,
            ),
        )
    )

    assert (
        result["restored_active_count"]
        == 1
    )

    assert (
        result[
            "restored_pending_exit_count"
        ]
        == 0
    )

    snap = coordinator.ce_shadow.snapshot

    assert snap is not None
    assert snap.status == "ACTIVE"

    assert list(
        snap.shadow_selected_instrument_keys
    ) == payload[
        "shadow_selected_instrument_keys"
    ]

    assert [
        x.instrument_key
        for x in snap.legs
    ] == payload[
        "shadow_selected_instrument_keys"
    ]


def test_pending_exit_restores_to_pending_store(tmp_path):
    coordinator = _coordinator(
        tmp_path,
        owner="NONE",
    )

    payload = _payload(
        direction="BEARISH",
        status="PENDING_EXACT_EXIT",
    )

    _append(
        coordinator,
        direction="BEARISH",
        stage="EXIT",
        payload=payload,
    )

    result = (
        coordinator
        ._restore_audited_option_state(
            now=datetime(
                2026,
                9,
                25,
                13,
                11,
                tzinfo=IST,
            ),
            session_date=date(
                2026,
                9,
                25,
            ),
        )
    )

    key = payload["signal_bar"]

    assert (
        result[
            "restored_pending_exit_count"
        ]
        == 1
    )

    assert (
        key
        in coordinator._pending_pe_exits
    )

    restored = (
        coordinator
        ._pending_pe_exits[key]
        .snapshot
    )

    assert (
        restored.status
        == "PENDING_EXACT_EXIT"
    )

    assert list(
        restored.shadow_selected_instrument_keys
    ) == payload[
        "shadow_selected_instrument_keys"
    ]

    # Pending exit must not occupy the current active PE slot.
    assert coordinator.pe_shadow.snapshot is None


def test_closed_recovery_supersedes_old_incomplete(tmp_path):
    coordinator = _coordinator(
        tmp_path,
        owner="NONE",
    )

    incomplete = _payload(
        direction="BEARISH",
        status="ACTIVE",
    )

    # Represent original START INCOMPLETE safely enough for planner.
    incomplete["status"] = "INCOMPLETE"
    incomplete["active"] = False
    incomplete["issue"] = (
        "AUDITED|-2:"
        "MISSING_ENTRY_MINUTE:"
        "2026-09-25T12:45:00+05:30"
    )

    _append(
        coordinator,
        direction="BEARISH",
        stage="START",
        payload=incomplete,
    )

    closed = _payload(
        direction="BEARISH",
        status="ACTIVE",
    )

    closed["status"] = "CLOSED"
    closed["active"] = False

    for leg in closed["legs"]:
        leg["exit_timestamp"] = (
            "2026-09-25T13:10:00+05:30"
        )
        leg["exit_open"] = (
            leg["entry_open"] + 2.0
        )
        leg["realized_points"] = 2.0
        leg["realized_return_pct"] = 1.0

    _append(
        coordinator,
        direction="BEARISH",
        stage="RECOVERY",
        payload=closed,
    )

    plan = (
        coordinator
        ._audited_option_restore_plan(
            date(
                2026,
                9,
                25,
            )
        )
    )

    assert plan["restorable"] == []
    assert plan["blocked"] == []


def test_incomplete_identity_fails_closed_on_restart(tmp_path):
    coordinator = _coordinator(
        tmp_path,
        owner="BEARISH",
    )

    payload = _payload(
        direction="BEARISH",
        status="ACTIVE",
    )

    payload["status"] = "INCOMPLETE"
    payload["active"] = False
    payload["issue"] = (
        "AUDITED|0:"
        "MISSING_ENTRY_MINUTE:"
        "2026-09-25T12:45:00+05:30"
    )

    _append(
        coordinator,
        direction="BEARISH",
        stage="START",
        payload=payload,
    )

    result = (
        coordinator
        ._restore_audited_option_state(
            now=datetime(
                2026,
                9,
                25,
                13,
                0,
                tzinfo=IST,
            ),
            session_date=date(
                2026,
                9,
                25,
            ),
        )
    )

    assert (
        result["restored_active_count"]
        == 0
    )

    assert (
        result["blocked_restore_count"]
        == 1
    )

    assert (
        coordinator.pe_shadow.snapshot
        is None
    )

    assert (
        coordinator._pending_pe_entries
        == {}
    )


def test_active_restart_continues_exact_audited_lifecycle_without_contract_lookup(
    tmp_path,
):
    from datetime import timedelta

    from market_lab.live_option_minute_source_v1 import (
        CompletedOptionMinute,
    )

    first = _coordinator(
        tmp_path,
        owner="BULLISH",
    )

    payload = _payload(
        direction="BULLISH",
        status="ACTIVE",
    )

    _append(
        first,
        direction="BULLISH",
        stage="START",
        payload=payload,
    )

    class Source:
        def __init__(self):
            self.contract_calls = 0

        def option_contracts(self, *args, **kwargs):
            self.contract_calls += 1
            raise AssertionError(
                "restart continuation must not resolve contracts"
            )

        def option_intraday_1m(self, key):
            leg = next(
                x
                for x in payload["legs"]
                if x["instrument_key"] == key
            )

            base = datetime(
                2026,
                9,
                25,
                12,
                45,
                tzinfo=IST,
            )

            rows = []

            for i in range(6):
                px = float(leg["entry_open"]) + i

                rows.append(
                    CompletedOptionMinute(
                        instrument_key=key,
                        timestamp=base + timedelta(minutes=i),
                        open=px,
                        high=px + 1.0,
                        low=px - 1.0,
                        close=px + 0.5,
                        volume=100.0,
                    )
                )

            return rows

    restarted = _coordinator(
        tmp_path,
        owner="BULLISH",
    )

    source = Source()
    restarted.sources = source

    result = restarted._restore_audited_option_state(
        now=datetime(
            2026,
            9,
            25,
            12,
            50,
            30,
            tzinfo=IST,
        ),
        session_date=date(
            2026,
            9,
            25,
        ),
    )

    assert result["restored_active_count"] == 1
    assert result["restored_pending_exit_count"] == 0
    assert source.contract_calls == 0

    before_keys = list(
        restarted.ce_shadow.snapshot
        .shadow_selected_instrument_keys
    )

    assert before_keys == payload[
        "shadow_selected_instrument_keys"
    ]

    # At 12:51 the latest completed option minute is exactly 12:50.
    restarted._update_options(
        datetime(
            2026,
            9,
            25,
            12,
            51,
            0,
            tzinfo=IST,
        )
    )

    snap = restarted.ce_shadow.snapshot

    assert snap is not None
    assert snap.status == "ACTIVE"
    assert snap.latest_completed_minute == (
        "2026-09-25T12:50:00+05:30"
    )

    assert list(
        snap.shadow_selected_instrument_keys
    ) == before_keys

    assert source.contract_calls == 0

    rows = restarted.step_audit.read_all()

    restore_rows = [
        x for x in rows
        if x.get("stage")
        == "BULLISH_OPTION_SHADOW_BOOTSTRAP_RESTORE"
    ]

    assert restore_rows

    restore_payload = (
        restore_rows[-1].get("payload") or {}
    )

    assert (
        restore_payload["identity_source"]
        == "AUDITED_OPTION_SNAPSHOT"
    )
    assert restore_payload["reconstructed"] is True
    assert (
        restore_payload["contract_master_lookup"]
        is False
    )

    starts = [
        x for x in rows
        if x.get("stage")
        == "BULLISH_OPTION_SHADOW_START"
    ]

    # Only the original audited START exists.
    assert len(starts) == 1

    updates = [
        x for x in rows
        if x.get("stage")
        == "BULLISH_OPTION_SHADOW_UPDATE"
    ]

    assert updates
    assert (
        updates[-1]["payload"][
            "latest_completed_minute"
        ]
        == "2026-09-25T12:50:00+05:30"
    )

    assert (
        restarted.step_audit.verify_chain()
        == (True, None)
    )


def test_pending_exit_restart_waits_then_closes_exact_boundary_without_contract_lookup(
    tmp_path,
):
    from market_lab.live_option_minute_source_v1 import (
        CompletedOptionMinute,
    )

    first = _coordinator(
        tmp_path,
        owner="NONE",
    )

    payload = _payload(
        direction="BEARISH",
        status="PENDING_EXACT_EXIT",
    )

    _append(
        first,
        direction="BEARISH",
        stage="EXIT",
        payload=payload,
    )

    exit_boundary = datetime.fromisoformat(
        payload["pending_exit_boundary"]
    )

    class Source:
        def __init__(self):
            self.exact_available = False
            self.contract_calls = 0

        def option_contracts(self, *args, **kwargs):
            self.contract_calls += 1
            raise AssertionError(
                "pending-exit restart must not resolve contracts"
            )

        def option_intraday_1m(self, key):
            if not self.exact_available:
                return []

            leg = next(
                x
                for x in payload["legs"]
                if x["instrument_key"] == key
            )

            px = float(leg["entry_open"]) + 25.0

            return [
                CompletedOptionMinute(
                    instrument_key=key,
                    timestamp=exit_boundary,
                    open=px,
                    high=px + 1.0,
                    low=px - 1.0,
                    close=px + 0.5,
                    volume=100.0,
                )
            ]

    restarted = _coordinator(
        tmp_path,
        owner="NONE",
    )

    source = Source()
    restarted.sources = source

    result = restarted._restore_audited_option_state(
        now=datetime(
            2026,
            9,
            25,
            13,
            11,
            0,
            tzinfo=IST,
        ),
        session_date=date(
            2026,
            9,
            25,
        ),
    )

    key = payload["signal_bar"]

    assert result["restored_active_count"] == 0
    assert result["restored_pending_exit_count"] == 1
    assert key in restarted._pending_pe_exits
    assert source.contract_calls == 0

    frozen_keys = list(
        restarted._pending_pe_exits[key]
        .snapshot
        .shadow_selected_instrument_keys
    )

    assert frozen_keys == payload[
        "shadow_selected_instrument_keys"
    ]

    # Exact 13:10 minute still unavailable.
    restarted._retry_pending(
        datetime(
            2026,
            9,
            25,
            13,
            11,
            0,
            tzinfo=IST,
        )
    )

    assert key in restarted._pending_pe_exits

    pending = (
        restarted._pending_pe_exits[key]
        .snapshot
    )

    assert pending.status == "PENDING_EXACT_EXIT"
    assert all(
        leg.exit_open is None
        for leg in pending.legs
    )

    # Exact original exit minute appears later.
    source.exact_available = True

    restarted._retry_pending(
        datetime(
            2026,
            9,
            25,
            13,
            12,
            0,
            tzinfo=IST,
        )
    )

    assert key not in restarted._pending_pe_exits
    assert source.contract_calls == 0

    rows = restarted.step_audit.read_all()

    restore_rows = [
        x for x in rows
        if x.get("stage")
        == "BEARISH_OPTION_SHADOW_BOOTSTRAP_RESTORE"
    ]

    assert restore_rows

    restore_payload = (
        restore_rows[-1].get("payload") or {}
    )

    assert (
        restore_payload["identity_source"]
        == "AUDITED_OPTION_SNAPSHOT"
    )
    assert restore_payload["reconstructed"] is True
    assert (
        restore_payload["contract_master_lookup"]
        is False
    )

    retries = [
        x for x in rows
        if x.get("stage")
        == "BEARISH_OPTION_SHADOW_EXIT_RETRY"
    ]

    assert len(retries) >= 2

    closed = retries[-1]["payload"]

    assert closed["status"] == "CLOSED"
    assert (
        closed["pending_exit_boundary"]
        is None
    )

    assert all(
        leg["exit_timestamp"]
        == "2026-09-25T13:10:00+05:30"
        for leg in closed["legs"]
    )

    expected_by_key = {
        leg["instrument_key"]:
        float(leg["entry_open"]) + 25.0
        for leg in payload["legs"]
    }

    assert all(
        leg["exit_open"]
        == expected_by_key[leg["instrument_key"]]
        for leg in closed["legs"]
    )

    assert [
        leg["instrument_key"]
        for leg in closed["legs"]
    ] == frozen_keys

    assert (
        restarted.step_audit.verify_chain()
        == (True, None)
    )
