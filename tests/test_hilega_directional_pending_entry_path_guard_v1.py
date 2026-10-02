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
            (
                22950.0,
                -2,
                "NSE_FO|A",
            ),
            (
                23000.0,
                -1,
                "NSE_FO|B",
            ),
            (
                23050.0,
                0,
                "NSE_FO|C",
            ),
            (
                23100.0,
                1,
                "NSE_FO|D",
            ),
            (
                23150.0,
                2,
                "NSE_FO|E",
            ),
        )
    )


def test_pending_entry_does_not_close_until_full_exact_path_exists():
    signal_bar = datetime(
        2026,
        9,
        25,
        12,
        40,
        tzinfo=IST,
    )

    entry_boundary = signal_bar + timedelta(
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

    missing_path_minute = datetime(
        2026,
        9,
        25,
        12,
        47,
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

    # --------------------------------------------------
    # 1. Exact entry minute is initially unavailable.
    # --------------------------------------------------

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

    # --------------------------------------------------
    # 2. Directional strategy exits while entry remains
    #    unavailable. Preserve lifecycle + exact exit.
    # --------------------------------------------------

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

    assert (
        key
        in coordinator._pending_pe_entries
    )

    assert (
        key
        in coordinator._pending_pe_entry_exits
    )

    # --------------------------------------------------
    # 3. Broker history later exposes entry + entire path
    #    except exact 12:47.
    # --------------------------------------------------

    base_opens = {
        "NSE_FO|A": 51.50,
        "NSE_FO|B": 66.20,
        "NSE_FO|C": 84.25,
        "NSE_FO|D": 105.65,
        "NSE_FO|E": 132.15,
    }

    for instrument_key, entry_open in (
        base_opens.items()
    ):
        instrument_rows = []

        ts = entry_boundary

        while ts <= exit_boundary:
            if ts != missing_path_minute:
                minute_offset = int(
                    (
                        ts - entry_boundary
                    ).total_seconds()
                    // 60
                )

                open_ = (
                    entry_open
                    + minute_offset * 0.10
                )

                instrument_rows.append(
                    Candle(
                        ts,
                        instrument_key,
                        open_,
                        open_ + 1.0,
                        open_ - 1.0,
                        open_ + 0.25,
                    )
                )

            ts += timedelta(minutes=1)

        rows[
            instrument_key
        ] = instrument_rows

    coordinator._retry_pending(
        datetime(
            2026,
            9,
            25,
            13,
            11,
            tzinfo=IST,
        )
    )

    # Entry should now be recovered and remain frozen.
    pending = (
        coordinator
        ._pending_pe_entries[
            key
        ]
    )

    recovered_entry = pending.snapshot

    assert recovered_entry is not None
    assert recovered_entry.status == "ACTIVE"
    assert recovered_entry.active is True

    assert (
        recovered_entry.signal_boundary
        == entry_boundary.isoformat()
    )

    assert len(
        recovered_entry.legs
    ) == 5

    actual_entries = {
        leg.instrument_key:
        leg.entry_open
        for leg in recovered_entry.legs
    }

    assert actual_entries == base_opens

    # Critical safety assertion:
    # missing 12:47 means the trade MUST remain pending.
    assert (
        key
        in coordinator._pending_pe_entries
    )

    assert (
        key
        in coordinator._pending_pe_entry_exits
    )

    assert (
        key
        not in coordinator._pending_pe_exits
    )

    assert not any(
        x["stage"]
        == "BEARISH_OPTION_SHADOW_EXIT_RETRY"
        and x["payload"].get(
            "status"
        )
        == "CLOSED"
        for x in audit
    )

    incomplete_updates = [
        x
        for x in audit
        if (
            x["stage"]
            == "BEARISH_OPTION_SHADOW_UPDATE"
            and x["status"]
            == "INCOMPLETE_UPDATE"
        )
    ]

    assert incomplete_updates

    assert (
        "MISSING_EXACT_MINUTE:"
        + missing_path_minute.isoformat()
        in incomplete_updates[-1][
            "payload"
        ]["issue"]
    )

    # --------------------------------------------------
    # 4. Exact missing 12:47 minute becomes available.
    # --------------------------------------------------

    for instrument_key, entry_open in (
        base_opens.items()
    ):
        minute_offset = int(
            (
                missing_path_minute
                - entry_boundary
            ).total_seconds()
            // 60
        )

        open_ = (
            entry_open
            + minute_offset * 0.10
        )

        rows[
            instrument_key
        ].append(
            Candle(
                missing_path_minute,
                instrument_key,
                open_,
                open_ + 1.0,
                open_ - 1.0,
                open_ + 0.25,
            )
        )

        rows[
            instrument_key
        ].sort(
            key=lambda x: x.timestamp
        )

    coordinator._retry_pending(
        datetime(
            2026,
            9,
            25,
            13,
            12,
            tzinfo=IST,
        )
    )

    # --------------------------------------------------
    # 5. Same frozen trade can now close exactly.
    # --------------------------------------------------

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

    closed_events = [
        x
        for x in audit
        if (
            x["stage"]
            == "BEARISH_OPTION_SHADOW_EXIT_RETRY"
            and x["payload"].get(
                "status"
            )
            == "CLOSED"
        )
    ]

    assert len(
        closed_events
    ) == 1

    closed = closed_events[0][
        "payload"
    ]

    assert (
        closed["signal_boundary"]
        == entry_boundary.isoformat()
    )

    assert (
        closed["latest_completed_minute"]
        == (
            exit_boundary
            - timedelta(minutes=1)
        ).isoformat()
    )

    assert (
        closed["pending_exit_boundary"]
        is None
    )

    assert len(
        closed["legs"]
    ) == 5

    assert {
        leg["instrument_key"]:
        leg["entry_open"]
        for leg in closed["legs"]
    } == base_opens

    assert all(
        leg["exit_timestamp"]
        == exit_boundary.isoformat()
        for leg in closed["legs"]
    )
