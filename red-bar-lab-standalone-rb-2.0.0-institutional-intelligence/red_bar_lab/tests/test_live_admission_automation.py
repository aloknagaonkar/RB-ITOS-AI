from datetime import datetime, timedelta
from types import SimpleNamespace
from zoneinfo import ZoneInfo

from red_bar_lab.execution.live_admission_automation import (
    LiveAdmissionRedBarPaperAutomationService,
    _AdmissionDatabaseProxy,
)


IST = ZoneInfo("Asia/Kolkata")


class _Database:
    def __init__(self, rows, queue=None):
        self.rows = list(rows)
        self.queue = list(queue or [])
        self.diagnostics = []
        self.events = []
        self.expired = []

    def read_signal_attempts(self, instrument_key, trading_date):
        return list(self.rows)

    def read_execution_queue(self):
        return list(self.queue)

    def expire_execution_queue_for_signal(self, *, signal_id, reason):
        self.expired.append((signal_id, reason))
        for row in self.queue:
            if row.get("signal_id") == signal_id and row.get("status") == "APPROVED":
                row["status"] = "EXPIRED"
                row["reason"] = reason

    def insert_paper_signal_diagnostic(self, row):
        self.diagnostics.append(dict(row))

    def insert_execution_state_event(self, row):
        self.events.append(dict(row))


def _proxy(database, now):
    return _AdmissionDatabaseProxy(
        database,
        now=now,
        max_signal_age_seconds=180,
        allow_outside_market_hours=False,
        allow_stale_signals=False,
        enable_opportunity_extension=True,
    )


def _service(database, *, enable_opportunity_extension=False):
    service = object.__new__(LiveAdmissionRedBarPaperAutomationService)
    service.database = database
    service.underlying_name = "NIFTY 50"
    service.max_signal_age_seconds = 180
    service.allow_outside_market_hours = False
    service.allow_stale_signals = False
    service.enable_opportunity_extension = enable_opportunity_extension
    return service


def test_terminal_live_block_is_filtered_before_legacy_engine():
    now = datetime(2026, 8, 21, 10, 0, tzinfo=IST)
    database = _Database(
        [
            {
                "signal_id": "SIG-MISSING",
                "confirmation_timestamp": None,
                "direction": "BULLISH",
                "state": "CONFIRMED",
            },
            {
                "signal_id": "SIG-FRESH",
                "confirmation_timestamp": now - timedelta(seconds=30),
                "direction": "BEARISH",
                "state": "CONFIRMED",
            },
        ]
    )

    rows = _proxy(database, now).read_signal_attempts("NIFTY", "2026-08-21")

    assert [row["signal_id"] for row in rows] == ["SIG-FRESH"]
    assert database.diagnostics[0]["reason"] == (
        "SIGNAL_CONFIRMATION_TIMESTAMP_MISSING"
    )
    assert database.events[0]["state"] == "LIVE_ADMISSION_BLOCKED"
    assert "historical_override=PROHIBITED" in database.events[0]["detail"]


def test_stale_signal_reaches_existing_opportunity_extension_path():
    now = datetime(2026, 8, 21, 10, 0, tzinfo=IST)
    database = _Database(
        [
            {
                "signal_id": "SIG-STALE",
                "confirmation_timestamp": now - timedelta(minutes=6),
                "direction": "BULLISH",
                "state": "CONFIRMED",
            }
        ]
    )

    proxy = _proxy(database, now)
    rows = proxy.read_signal_attempts("NIFTY", "2026-08-21")

    assert [row["signal_id"] for row in rows] == ["SIG-STALE"]
    assert proxy.decisions["SIG-STALE"].requires_opportunity_extension is True
    assert database.diagnostics == []
    assert database.events == []


def test_queue_consumer_expires_terminally_blocked_approved_signal():
    now = datetime(2026, 8, 21, 10, 0, tzinfo=IST)
    database = _Database(
        [
            {
                "signal_id": "SIG-BLOCKED",
                "confirmation_timestamp": None,
                "direction": "BULLISH",
                "state": "CONFIRMED",
            }
        ],
        queue=[
            {
                "queue_id": "Q-1",
                "signal_id": "SIG-BLOCKED",
                "status": "APPROVED",
            },
            {
                "queue_id": "Q-2",
                "signal_id": "SIG-BLOCKED",
                "status": "APPROVED",
            },
        ],
    )
    service = _service(database)

    blocked = service._enforce_queue_admission(
        trading_date="2026-08-21",
        now=now,
    )

    assert blocked == 1
    assert database.expired == [
        (
            "SIG-BLOCKED",
            "LIVE_ADMISSION:SIGNAL_CONFIRMATION_TIMESTAMP_MISSING",
        )
    ]
    assert all(row["status"] == "EXPIRED" for row in database.queue)
    assert database.diagnostics[0]["scan_id"] == "LIVE-ADMISSION-QUEUE"
    assert database.events[0]["state"] == "LIVE_ADMISSION_QUEUE_BLOCKED"
    assert "historical_override=PROHIBITED" in database.events[0]["detail"]


def test_queue_consumer_preserves_fresh_and_unresolved_approved_rows():
    now = datetime(2026, 8, 21, 10, 0, tzinfo=IST)
    database = _Database(
        [
            {
                "signal_id": "SIG-FRESH",
                "confirmation_timestamp": now - timedelta(seconds=30),
                "direction": "BEARISH",
                "state": "CONFIRMED",
            }
        ],
        queue=[
            {
                "queue_id": "Q-FRESH",
                "signal_id": "SIG-FRESH",
                "status": "APPROVED",
            },
            {
                "queue_id": "Q-OTHER-SOURCE",
                "signal_id": "SIG-NOT-IN-RED-BAR-SIGNALS",
                "status": "APPROVED",
            },
        ],
    )
    service = _service(database)

    blocked = service._enforce_queue_admission(
        trading_date="2026-08-21",
        now=now,
    )

    assert blocked == 0
    assert database.expired == []
    assert all(row["status"] == "APPROVED" for row in database.queue)
    assert database.diagnostics == []
    assert database.events == []


def test_executed_signal_is_skipped_not_reblocked_or_readmitted():
    # Regression for the 2026-09-01 failure: a signal confirmed at 09:30 that
    # already opened a paper order must not be BLOCKed with
    # MAX_SIGNAL_AGE_EXCEEDED (and spam diagnostics) nor re-admitted into the
    # execution pipeline once the 180-second age gate has passed.
    now = datetime(2026, 9, 1, 9, 40, tzinfo=IST)
    database = _Database(
        [
            {
                "signal_id": "SIG-EXECUTED",
                "confirmation_timestamp": now - timedelta(minutes=10),
                "direction": "BULLISH",
                "state": "ACTIVE",
            },
            {
                "signal_id": "SIG-FRESH",
                "confirmation_timestamp": now - timedelta(seconds=30),
                "direction": "BEARISH",
                "state": "CONFIRMED",
            },
        ],
        queue=[
            {
                "queue_id": "Q-EXEC",
                "signal_id": "SIG-EXECUTED",
                "status": "EXECUTED",
            },
        ],
    )
    database.orders = [
        {"signal_id": "SIG-EXECUTED", "status": "OPEN"},
    ]

    def _read_paper_execution_orders(account_id):
        return list(database.orders)

    database.read_paper_execution_orders = _read_paper_execution_orders

    proxy = _AdmissionDatabaseProxy(
        database,
        now=now,
        max_signal_age_seconds=180,
        allow_outside_market_hours=False,
        allow_stale_signals=False,
        enable_opportunity_extension=False,
        account_id="PAPER-STD",
    )

    rows = proxy.read_signal_attempts("NIFTY", "2026-09-01")

    # The executed signal is dropped entirely: fresh BEARISH signal only.
    assert [row["signal_id"] for row in rows] == ["SIG-FRESH"]
    # No BLOCK diagnostic spam for the already-executed signal.
    assert all(
        row["signal_id"] != "SIG-EXECUTED"
        for row in database.diagnostics
    )
    assert proxy.decisions["SIG-EXECUTED"].reason == (
        "SIGNAL_ALREADY_EXECUTED"
    )


def test_queue_consumer_does_not_expire_already_executed_signal():
    # An APPROVED row whose signal already produced an order must survive the
    # age gate: it should not be expired with MAX_SIGNAL_AGE_EXCEEDED.
    now = datetime(2026, 9, 1, 9, 40, tzinfo=IST)
    database = _Database(
        [
            {
                "signal_id": "SIG-EXECUTED",
                "confirmation_timestamp": now - timedelta(minutes=10),
                "direction": "BULLISH",
                "state": "ACTIVE",
            }
        ],
        queue=[
            {
                "queue_id": "Q-APPROVED",
                "signal_id": "SIG-EXECUTED",
                "status": "APPROVED",
            },
        ],
    )
    database.orders = [
        {"signal_id": "SIG-EXECUTED", "status": "OPEN"},
    ]

    def _read_paper_execution_orders(account_id):
        return list(database.orders)

    database.read_paper_execution_orders = _read_paper_execution_orders

    service = _service(database)
    service.engine = SimpleNamespace(account_id="PAPER-STD")

    blocked = service._enforce_queue_admission(
        trading_date="2026-09-01",
        now=now,
    )

    assert blocked == 0
    assert database.expired == []
    assert all(row["status"] == "APPROVED" for row in database.queue)
    assert database.diagnostics == []
    assert database.events == []


def test_workspace_installs_additive_live_admission_service():
    from red_bar_lab.ui import workspace
    from red_bar_lab.ui import _shared

    assert workspace.shared_ui.RedBarPaperAutomationService is (
        LiveAdmissionRedBarPaperAutomationService
    )
    assert _shared.RedBarPaperAutomationService is (
        LiveAdmissionRedBarPaperAutomationService
    )
