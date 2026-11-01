from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from market_lab.hilega_directional_live_shadow_v1 import (
    HilegaDirectionalLiveShadowCoordinatorV1,
)

IST = ZoneInfo("Asia/Kolkata")


def test_exact_missing_entry_retries_original_boundary_and_becomes_active():
    class Candle:
        def __init__(self, timestamp, instrument_key, open_, high, low, close):
            self.timestamp = timestamp
            self.instrument_key = instrument_key
            self.open = open_
            self.high = high
            self.low = low
            self.close = close
            self.volume = 1000.0

    class Candidate:
        def __init__(self, strike, relation, instrument_key):
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

    signal_bar = datetime(
        2026, 9, 25, 12, 40,
        tzinfo=IST,
    )
    boundary = signal_bar + timedelta(minutes=5)

    rows = {}

    class Sources:
        def option_intraday_1m(self, instrument_key):
            return rows.get(instrument_key, [])

    # Avoid constructing the full production coordinator.
    coordinator = object.__new__(
        HilegaDirectionalLiveShadowCoordinatorV1
    )

    from market_lab.hilega_milega_pe_option_shadow_lifecycle_v1 import (
        HilegaMilegaPEOptionShadowLifecycleV1,
    )
    from market_lab.hilega_milega_option_shadow_lifecycle_v1 import (
        HilegaMilegaOptionShadowLifecycleV1,
    )

    coordinator.sources = Sources()
    coordinator.pe_shadow = HilegaMilegaPEOptionShadowLifecycleV1()
    coordinator.ce_shadow = HilegaMilegaOptionShadowLifecycleV1()
    coordinator._pending_ce_exits = {}
    coordinator._pending_pe_exits = {}

    coordinator._pending_ce_entries = {}
    coordinator._pending_pe_entries = {}
    coordinator._pending_ce_entry_exits = {}
    coordinator._pending_pe_entry_exits = {}

    coordinator._ce_last_update = None
    coordinator._pe_last_update = None

    audit = []

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

    snap = coordinator.pe_shadow.start(
        signal_bar_ts=signal_bar,
        signal_spot=23056.75,
        source="BEARISH_ROUTE_B_STRUCTURAL",
        candidate_set=CandidateSet(),
        option_minutes=coordinator.sources.option_intraday_1m,
    )

    assert snap.status == "INCOMPLETE"
    assert snap.active is False
    assert snap.signal_boundary == boundary.isoformat()
    assert len(snap.legs) == 0

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

    coordinator._retry_pending(
        datetime(
            2026, 9, 25, 12, 46,
            tzinfo=IST,
        )
    )

    recovered = coordinator.pe_shadow.snapshot

    assert recovered is not None
    assert recovered.status == "ACTIVE"
    assert recovered.active is True
    assert recovered.signal_bar == signal_bar.isoformat()
    assert recovered.signal_boundary == boundary.isoformat()
    assert len(recovered.legs) == 5

    actual = {
        leg.instrument_key: leg.entry_open
        for leg in recovered.legs
    }

    assert actual == opens

    retry_events = [
        x for x in audit
        if x["stage"]
        == "BEARISH_OPTION_SHADOW_ENTRY_RETRY"
    ]

    assert retry_events
    assert retry_events[-1]["status"] == "PASS"
    assert (
        retry_events[-1]["payload"]["signal_boundary"]
        == boundary.isoformat()
    )


def test_missing_entry_survives_strategy_exit_then_recovers_exact_closed_trade():
    from market_lab.hilega_milega_option_shadow_lifecycle_v1 import (
        HilegaMilegaOptionShadowLifecycleV1,
    )
    from market_lab.hilega_milega_pe_option_shadow_lifecycle_v1 import (
        HilegaMilegaPEOptionShadowLifecycleV1,
    )

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

    signal_bar = datetime(
        2026, 9, 25, 12, 40,
        tzinfo=IST,
    )

    entry_boundary = signal_bar + timedelta(
        minutes=5
    )

    exit_boundary = datetime(
        2026, 9, 25, 12, 50,
        tzinfo=IST,
    )

    rows = {}

    class Sources:
        def option_intraday_1m(
            self,
            instrument_key,
        ):
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

    audit = []

    def record_audit(
        now,
        stage,
        status,
        payload,
        checkpoint=None,
    ):
        audit.append(
            {
                "event_time": now,
                "stage": stage,
                "status": status,
                "payload": payload,
                "checkpoint": checkpoint,
            }
        )

    coordinator._audit = record_audit

    # ------------------------------------------------------
    # 1. Strategy entry exists, but exact 12:45 option OPEN
    #    is unavailable.
    # ------------------------------------------------------

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
    assert started.active is False
    assert len(started.legs) == 0

    # ------------------------------------------------------
    # 2. Underlying strategy exits at 12:50 while option
    #    entry is still unavailable.
    #
    #    Lifecycle must be preserved in pending-entry store,
    #    not discarded.
    # ------------------------------------------------------

    coordinator._close_option(
        direction="BEARISH",
        now=datetime(
            2026, 9, 25, 12, 50, 30,
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

    assert key in coordinator._pending_pe_entries
    assert key in coordinator._pending_pe_entry_exits

    # Active slot must be free for future PE signals.
    assert coordinator.pe_shadow.snapshot is None

    waiting = [
        x
        for x in audit
        if x["stage"]
        == "BEARISH_OPTION_SHADOW_EXIT_WAITING_FOR_ENTRY"
    ]

    assert waiting
    assert waiting[-1]["status"] == "PENDING_EXACT_ENTRY"
    assert (
        waiting[-1]["payload"]["deferred_exit_boundary"]
        == exit_boundary.isoformat()
    )

    # ------------------------------------------------------
    # 3. Exact historical option evidence later appears.
    #
    #    Supply EVERY exact minute:
    #       entry 12:45
    #       updates 12:46-12:49
    #       exit OPEN 12:50
    # ------------------------------------------------------

    entry_opens = {
        "NSE_FO|A": 51.50,
        "NSE_FO|B": 66.20,
        "NSE_FO|C": 84.25,
        "NSE_FO|D": 105.65,
        "NSE_FO|E": 132.15,
    }

    exit_opens = {
        "NSE_FO|A": 57.50,
        "NSE_FO|B": 72.20,
        "NSE_FO|C": 90.25,
        "NSE_FO|D": 111.65,
        "NSE_FO|E": 138.15,
    }

    for key_name, entry_open in entry_opens.items():
        path = []

        # 12:45 through 12:49
        for offset in range(5):
            ts = entry_boundary + timedelta(
                minutes=offset
            )

            open_ = entry_open + offset

            path.append(
                Candle(
                    ts,
                    key_name,
                    open_,
                    open_ + 2.0,
                    open_ - 1.0,
                    open_ + 1.0,
                )
            )

        # Exact causal exit OPEN at 12:50.
        exit_open = exit_opens[key_name]

        path.append(
            Candle(
                exit_boundary,
                key_name,
                exit_open,
                exit_open + 1.0,
                exit_open - 1.0,
                exit_open + 0.5,
            )
        )

        rows[key_name] = path

    # ------------------------------------------------------
    # 4. Retry.
    #
    #    Expected:
    #       INCOMPLETE
    #        -> ACTIVE at exact 12:45
    #        -> exact path through 12:49
    #        -> CLOSED at exact 12:50 OPEN
    # ------------------------------------------------------

    coordinator._retry_pending(
        datetime(
            2026, 9, 25, 12, 51,
            tzinfo=IST,
        )
    )

    # Recovered trade must be removed from pending-entry
    # collections after successfully closing.
    assert (
        signal_bar.isoformat()
        not in coordinator._pending_pe_entries
    )

    assert (
        signal_bar.isoformat()
        not in coordinator._pending_pe_entry_exits
    )

    # It must not require pending-exit recovery because the
    # exact 12:50 OPEN was available.
    assert (
        signal_bar.isoformat()
        not in coordinator._pending_pe_exits
    )

    entry_retry = [
        x
        for x in audit
        if (
            x["stage"]
            == "BEARISH_OPTION_SHADOW_ENTRY_RETRY"
            and x["status"] == "PASS"
        )
    ]

    assert entry_retry

    recovered_entry = entry_retry[-1]["payload"]

    assert recovered_entry["status"] == "ACTIVE"
    assert (
        recovered_entry["signal_boundary"]
        == entry_boundary.isoformat()
    )

    assert len(
        recovered_entry["legs"]
    ) == 5

    recovered_opens = {
        leg["instrument_key"]: leg["entry_open"]
        for leg in recovered_entry["legs"]
    }

    assert recovered_opens == entry_opens

    closed = [
        x
        for x in audit
        if (
            x["stage"]
            == "BEARISH_OPTION_SHADOW_EXIT_RETRY"
            and x["status"] == "PASS"
            and x["payload"]["status"] == "CLOSED"
        )
    ]

    assert closed

    final = closed[-1]["payload"]

    assert final["signal_bar"] == signal_bar.isoformat()
    assert (
        final["signal_boundary"]
        == entry_boundary.isoformat()
    )

    assert final["exit_reason"] == (
        "STRUCTURAL_EXIT_BEARISH_"
        "RSI_CROSS_ABOVE_WMA21"
    )

    assert len(final["legs"]) == 5

    for leg in final["legs"]:
        key_name = leg["instrument_key"]

        assert (
            leg["entry_timestamp"]
            == entry_boundary.isoformat()
        )

        assert (
            leg["entry_open"]
            == entry_opens[key_name]
        )

        assert (
            leg["exit_timestamp"]
            == exit_boundary.isoformat()
        )

        assert (
            leg["exit_open"]
            == exit_opens[key_name]
        )

        assert (
            leg["realized_points"]
            == exit_opens[key_name]
            - entry_opens[key_name]
        )
