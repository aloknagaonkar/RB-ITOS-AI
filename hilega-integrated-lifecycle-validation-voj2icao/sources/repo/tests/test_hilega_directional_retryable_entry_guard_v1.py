from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from market_lab.hilega_directional_live_shadow_v1 import (
    HilegaDirectionalLiveShadowCoordinatorV1,
)
from market_lab.hilega_milega_option_shadow_lifecycle_v1 import (
    HilegaMilegaOptionShadowLifecycleV1,
)
from market_lab.hilega_milega_pe_option_shadow_lifecycle_v1 import (
    HilegaMilegaPEOptionShadowLifecycleV1,
)


IST = ZoneInfo("Asia/Kolkata")


class Candle:
    def __init__(
        self,
        timestamp,
        instrument_key,
        open_,
        high,
        low,
        close,
    ):
        self.timestamp = timestamp
        self.instrument_key = instrument_key
        self.open = open_
        self.high = high
        self.low = low
        self.close = close
        self.volume = 1000.0


class Candidate:
    def __init__(
        self,
        strike,
        relation,
        instrument_key,
    ):
        self.strike = strike
        self.relation_to_atm = relation
        self.instrument_key = instrument_key
        self.side = "PE"
        self.expiry = "2026-09-29"


class CandidateSet:
    status = "AVAILABLE"
    expiry = "2026-09-29"
    atm = 23050.0
    issue = None

    candidates = tuple(
        Candidate(
            strike,
            relation,
            key,
        )
        for strike, relation, key in (
            (22950.0, -2, "NSE_FO|A"),
            (23000.0, -1, "NSE_FO|B"),
            (23050.0, 0, "NSE_FO|C"),
            (23100.0, 1, "NSE_FO|D"),
            (23150.0, 2, "NSE_FO|E"),
        )
    )


def _coordinator(rows, audit):
    class Sources:
        def __init__(self):
            self.calls = 0

        def option_intraday_1m(
            self,
            instrument_key,
        ):
            self.calls += 1
            return rows.get(
                instrument_key,
                [],
            )

    coordinator = object.__new__(
        HilegaDirectionalLiveShadowCoordinatorV1
    )

    coordinator.sources = Sources()

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

    def record_audit(
        now,
        stage,
        status,
        payload,
        checkpoint=None,
    ):
        audit.append(
            {
                "stage": stage,
                "status": status,
                "payload": payload,
                "checkpoint": checkpoint,
            }
        )

    coordinator._audit = record_audit

    return coordinator


def test_only_missing_entry_minute_issue_is_retryable():
    class Snapshot:
        status = "INCOMPLETE"

        def __init__(self, issue):
            self.issue = issue

    assert (
        HilegaDirectionalLiveShadowCoordinatorV1
        ._retryable_missing_entry(
            Snapshot(
                "NSE_FO|A:"
                "MISSING_ENTRY_MINUTE:"
                "2026-09-25T12:45:00+05:30"
            )
        )
        is True
    )

    assert (
        HilegaDirectionalLiveShadowCoordinatorV1
        ._retryable_missing_entry(
            Snapshot(
                "NSE_FO|A:"
                "MISSING_ENTRY_MINUTE:"
                "2026-09-25T12:45:00+05:30;"
                "NSE_FO|B:"
                "MISSING_ENTRY_MINUTE:"
                "2026-09-25T12:45:00+05:30"
            )
        )
        is True
    )

    assert (
        HilegaDirectionalLiveShadowCoordinatorV1
        ._retryable_missing_entry(
            Snapshot(
                "NSE_FO|A:DUPLICATE_MINUTE"
            )
        )
        is False
    )

    assert (
        HilegaDirectionalLiveShadowCoordinatorV1
        ._retryable_missing_entry(
            Snapshot(
                "NSE_FO|A:"
                "MISSING_ENTRY_MINUTE:"
                "2026-09-25T12:45:00+05:30;"
                "NSE_FO|B:DUPLICATE_MINUTE"
            )
        )
        is False
    )

    assert (
        HilegaDirectionalLiveShadowCoordinatorV1
        ._retryable_missing_entry(
            Snapshot(
                "NSE_FO|A:"
                "NONPOSITIVE_ENTRY_OPEN"
            )
        )
        is False
    )

    assert (
        HilegaDirectionalLiveShadowCoordinatorV1
        ._retryable_missing_entry(
            Snapshot("")
        )
        is False
    )


def test_duplicate_entry_minute_is_not_retried():
    signal_bar = datetime(
        2026,
        9,
        25,
        12,
        40,
        tzinfo=IST,
    )

    boundary = signal_bar + timedelta(
        minutes=5
    )

    rows = {}
    audit = []

    opens = {
        "NSE_FO|A": 51.50,
        "NSE_FO|B": 66.20,
        "NSE_FO|C": 84.25,
        "NSE_FO|D": 105.65,
        "NSE_FO|E": 132.15,
    }

    for key, open_ in opens.items():
        rows[key] = [
            Candle(
                boundary,
                key,
                open_,
                open_ + 1,
                open_ - 1,
                open_ + 0.5,
            )
        ]

    # Duplicate timestamp for one frozen instrument.
    rows["NSE_FO|C"].append(
        Candle(
            boundary,
            "NSE_FO|C",
            84.30,
            85.30,
            83.30,
            84.80,
        )
    )

    coordinator = _coordinator(
        rows,
        audit,
    )

    started = coordinator.pe_shadow.start(
        signal_bar_ts=signal_bar,
        signal_spot=23056.75,
        source="BEARISH_ROUTE_B_STRUCTURAL",
        candidate_set=CandidateSet(),
        option_minutes=(
            coordinator.sources.option_intraday_1m
        ),
    )

    assert started.status == "INCOMPLETE"
    assert "DUPLICATE_MINUTE" in started.issue

    calls_after_start = (
        coordinator.sources.calls
    )

    coordinator._retry_pending(
        datetime(
            2026,
            9,
            25,
            12,
            46,
            tzinfo=IST,
        )
    )

    # Critical assertion:
    # retry_missing_entry must not call broker/evidence again.
    assert (
        coordinator.sources.calls
        == calls_after_start
    )

    blocked = [
        x
        for x in audit
        if (
            x["stage"]
            == "BEARISH_OPTION_SHADOW_ENTRY_RETRY"
            and x["status"]
            == "BLOCKED_NON_RETRYABLE_ENTRY"
        )
    ]

    assert len(blocked) == 1
    assert blocked[0]["payload"]["retryable"] is False
    assert (
        "DUPLICATE_MINUTE"
        in blocked[0]["payload"]["issue"]
    )

    assert (
        coordinator.pe_shadow.snapshot
        is started
    )


def test_nonretryable_incomplete_is_not_preserved_after_strategy_exit():
    signal_bar = datetime(
        2026,
        9,
        25,
        12,
        40,
        tzinfo=IST,
    )

    boundary = signal_bar + timedelta(
        minutes=5
    )

    exit_boundary = datetime(
        2026,
        9,
        25,
        13,
        10,
        tzinfo=IST,
    )

    rows = {}
    audit = []

    opens = {
        "NSE_FO|A": 51.50,
        "NSE_FO|B": 66.20,
        "NSE_FO|C": 84.25,
        "NSE_FO|D": 105.65,
        "NSE_FO|E": 132.15,
    }

    for key, open_ in opens.items():
        rows[key] = [
            Candle(
                boundary,
                key,
                open_,
                open_ + 1,
                open_ - 1,
                open_ + 0.5,
            )
        ]

    rows["NSE_FO|C"].append(
        Candle(
            boundary,
            "NSE_FO|C",
            84.30,
            85.30,
            83.30,
            84.80,
        )
    )

    coordinator = _coordinator(
        rows,
        audit,
    )

    started = coordinator.pe_shadow.start(
        signal_bar_ts=signal_bar,
        signal_spot=23056.75,
        source="BEARISH_ROUTE_B_STRUCTURAL",
        candidate_set=CandidateSet(),
        option_minutes=(
            coordinator.sources.option_intraday_1m
        ),
    )

    assert started.status == "INCOMPLETE"
    assert "DUPLICATE_MINUTE" in started.issue

    coordinator._close_option(
        direction="BEARISH",
        now=datetime(
            2026,
            9,
            25,
            13,
            5,
            30,
            tzinfo=IST,
        ),
        exit_boundary=exit_boundary,
        exit_reason=(
            "STRUCTURAL_EXIT_BEARISH_"
            "RSI_CROSS_ABOVE_WMA21"
        ),
        audit=True,
    )

    key = signal_bar.isoformat()

    # Permanent failures must not enter transient retry stores.
    assert (
        key
        not in coordinator._pending_pe_entries
    )

    assert (
        key
        not in coordinator._pending_pe_entry_exits
    )

    assert (
        key
        not in coordinator._pending_pe_exits
    )

    # Slot is released after directional ownership ends.
    assert coordinator.pe_shadow.snapshot is None

    blocked = [
        x
        for x in audit
        if (
            x["stage"]
            == "BEARISH_OPTION_SHADOW_EXIT_WAITING_FOR_ENTRY"
            and x["status"]
            == "BLOCKED_NON_RETRYABLE_ENTRY"
        )
    ]

    assert len(blocked) == 1
    assert blocked[0]["payload"]["retryable"] is False
    assert (
        "DUPLICATE_MINUTE"
        in blocked[0]["payload"]["issue"]
    )
