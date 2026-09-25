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
