"""The two Red Bar V2 entry gates that run inside ``process_new_signals``.

Both were on the agreed entry table and neither had any live enforcement:

* the rule table has no re-offer, so a V2 signal past its expiry is retired
  rather than evaluated again against prices that have since moved;
* gate 5 -- a priceable invalidation level, and risk inside the 8-60 point band
  -- was computed only in research.

These are behaviour tests over the real service and a real database. Each states
what the pipeline must do with one signal row, and the interesting half of each
is the negative: what must *not* be blocked. A gate that blocks everything is
indistinguishable from a broken feed.
"""

from datetime import datetime, timedelta
import sqlite3
from zoneinfo import ZoneInfo

from red_bar_lab.execution.automation import RedBarPaperAutomationService
from red_bar_lab.tests.test_execution_foundation import AutoFakeZerodha, _setup

IST = ZoneInfo("Asia/Kolkata")


def _insert_signal(
    db,
    *,
    signal_id,
    trading_date,
    confirmation_timestamp,
    level_type="RED_BAR_V2",
    risk_plan_tradable=None,
    risk_plan_code=None,
    risk_plan_detail=None,
    risk_stop_price=None,
    risk_points=None,
    risk_stop_trigger=None,
):
    """One ACTIVE signal row, with the frozen risk plan the gate reads."""
    with sqlite3.connect(db.path) as conn:
        conn.execute(
            """
            INSERT INTO signal_attempts(
                signal_id,run_id,instrument_key,trading_date,
                level_type,level_value,direction,state,
                confirmation_timestamp,underlying_entry,
                confirmation_high,confirmation_low,confirmation_close,
                risk_plan_tradable,risk_plan_code,risk_plan_detail,
                risk_stop_price,risk_points,risk_stop_trigger,
                created_at
            )
            VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                signal_id,
                "RUN-V2",
                "NSE_INDEX|Nifty 50",
                trading_date,
                level_type,
                25000.0,
                "BULLISH",
                "ACTIVE",
                confirmation_timestamp,
                25010.0,
                25030.0,
                24990.0,
                25010.0,
                risk_plan_tradable,
                risk_plan_code,
                risk_plan_detail,
                risk_stop_price,
                risk_points,
                risk_stop_trigger,
                confirmation_timestamp,
            ),
        )
        conn.commit()


def _service(db, settings, **overrides):
    kwargs = dict(
        zerodha=AutoFakeZerodha(),
        database=db,
        settings=settings,
        underlying_name="NIFTY 50",
        allow_outside_market_hours=True,
        max_signal_age_seconds=180,
    )
    kwargs.update(overrides)
    return RedBarPaperAutomationService(**kwargs)


def _states(db, signal_id):
    return [
        str(row["state"])
        for row in db.read_execution_state_events(signal_id=signal_id, limit=50)
    ]


def test_a_stale_v2_signal_is_retired_instead_of_re_offered(tmp_path):
    """The 2026-09-03 failure, as a test.

    That day one signal confirmed at 09:25 was still being offered at 15:13 --
    age 20,934 s -- and the only trade taken was a 25-minute-old signal admitted
    the same way, for -520. A V2 entry belongs to the completed close that
    qualified it; once that has aged out the strategy waits for the next one.
    """
    now = datetime.now(IST)
    trading_date = now.date().isoformat()
    settings, db = _setup(tmp_path)
    _insert_signal(
        db,
        signal_id="RBV2-STALE",
        trading_date=trading_date,
        confirmation_timestamp=(now - timedelta(minutes=25)).isoformat(),
    )
    service = _service(db, settings)

    opened, skipped, _scored, errors = service.process_new_signals(
        trading_date=trading_date, lots=1, queue_only=True
    )

    assert errors == []
    assert opened == 0
    assert skipped >= 1
    assert "RED_BAR_V2_SIGNAL_EXPIRED" in _states(db, "RBV2-STALE")


def test_a_fresh_v2_signal_is_not_touched_by_the_expiry_gate(tmp_path):
    """The gate is an age gate, not a V2 gate. A signal inside the window lives."""
    now = datetime.now(IST)
    trading_date = now.date().isoformat()
    settings, db = _setup(tmp_path)
    _insert_signal(
        db,
        signal_id="RBV2-FRESH",
        trading_date=trading_date,
        confirmation_timestamp=(now - timedelta(seconds=30)).isoformat(),
    )
    service = _service(db, settings)

    _opened, _skipped, _scored, errors = service.process_new_signals(
        trading_date=trading_date, lots=1, queue_only=True
    )

    assert errors == []
    states = _states(db, "RBV2-FRESH")
    assert "RED_BAR_V2_SIGNAL_EXPIRED" not in states
    # Reached the queue, so the absence above is a pass and not an early bail-out
    # somewhere upstream that would make this test agree with anything.
    assert "QUEUED" in states


def test_expiry_leaves_a_non_v2_source_of_the_same_age_alone(tmp_path):
    """Only V2's rule table forbids the re-offer, so only V2 rows are retired.

    Same age, same day, same everything but the source. RB-1.5.0's own policy is
    that age alone never blocks an otherwise healthy opportunity, and this change
    must not have quietly overturned it for every other strategy.
    """
    now = datetime.now(IST)
    trading_date = now.date().isoformat()
    settings, db = _setup(tmp_path)
    _insert_signal(
        db,
        signal_id="SIG-LEGACY",
        trading_date=trading_date,
        confirmation_timestamp=(now - timedelta(minutes=25)).isoformat(),
        level_type="TEST",
    )
    service = _service(db, settings)

    _opened, _skipped, _scored, errors = service.process_new_signals(
        trading_date=trading_date, lots=1, queue_only=True
    )

    assert errors == []
    states = _states(db, "SIG-LEGACY")
    assert "RED_BAR_V2_SIGNAL_EXPIRED" not in states
    # And it is the re-offer itself that survives, not merely the signal: the same
    # 25-minute age that retires a V2 row still earns a non-V2 one an extension.
    assert "OPPORTUNITY_EXTENSION_APPROVED" in states
    assert "QUEUED" in states


def test_a_refused_risk_plan_stops_the_entry_at_the_order_path(tmp_path):
    """Gate 5, finally live: no tradable stop, no order.

    The verdict is read, never recomputed. It was frozen at the qualifying minute
    from 5-minute bars truncated there; pricing it again now would read the
    finished slot and the entry would be judged on candles that printed after the
    decision.
    """
    now = datetime.now(IST)
    trading_date = now.date().isoformat()
    settings, db = _setup(tmp_path)
    _insert_signal(
        db,
        signal_id="RBV2-NOPLAN",
        trading_date=trading_date,
        confirmation_timestamp=(now - timedelta(seconds=30)).isoformat(),
        risk_plan_tradable=0,
        risk_plan_code="RISK_BELOW_FLOOR",
        risk_plan_detail="risk 5.4 points below floor 8.0",
        risk_stop_price=24996.0,
        risk_points=5.4,
        risk_stop_trigger="MIDPOINT_CROSS",
    )
    service = _service(db, settings)

    opened, skipped, _scored, errors = service.process_new_signals(
        trading_date=trading_date, lots=1, queue_only=True
    )

    assert errors == []
    assert opened == 0
    assert skipped >= 1
    states = _states(db, "RBV2-NOPLAN")
    assert "RED_BAR_V2_RISK_PLAN_REJECTED" in states

    detail = next(
        str(row["detail"])
        for row in db.read_execution_state_events(signal_id="RBV2-NOPLAN", limit=50)
        if str(row["state"]) == "RED_BAR_V2_RISK_PLAN_REJECTED"
    )
    # A refusal has to be auditable rather than trusted: the code, the arithmetic
    # behind it, and which candle set the level.
    assert "RISK_BELOW_FLOOR" in detail
    assert "5.4" in detail
    assert "MIDPOINT_CROSS" in detail


def test_a_tradable_risk_plan_passes_the_gate(tmp_path):
    """The gate's positive case, without which it proves nothing."""
    now = datetime.now(IST)
    trading_date = now.date().isoformat()
    settings, db = _setup(tmp_path)
    _insert_signal(
        db,
        signal_id="RBV2-PLANNED",
        trading_date=trading_date,
        confirmation_timestamp=(now - timedelta(seconds=30)).isoformat(),
        risk_plan_tradable=1,
        risk_plan_code="RISK_PLAN_OK",
        risk_plan_detail="risk 14.0 points",
        risk_stop_price=24996.0,
        risk_points=14.0,
        risk_stop_trigger="MIDPOINT_CROSS",
    )
    service = _service(db, settings)

    _opened, _skipped, _scored, errors = service.process_new_signals(
        trading_date=trading_date, lots=1, queue_only=True
    )

    assert errors == []
    states = _states(db, "RBV2-PLANNED")
    assert "RED_BAR_V2_RISK_PLAN_REJECTED" not in states
    assert "QUEUED" in states


def test_a_candle_outage_is_evidence_about_the_feed_not_a_refusal(tmp_path):
    """RISK_PLAN_UNAVAILABLE stays tradable, and deliberately.

    A missing candle series says nothing about whether *this* entry has a stop.
    Blocking on it would turn every feed hiccup into a silent trading halt that
    looks exactly like a strategy decision in the logs.
    """
    now = datetime.now(IST)
    trading_date = now.date().isoformat()
    settings, db = _setup(tmp_path)
    _insert_signal(
        db,
        signal_id="RBV2-OUTAGE",
        trading_date=trading_date,
        confirmation_timestamp=(now - timedelta(seconds=30)).isoformat(),
        risk_plan_tradable=1,
        risk_plan_code="RISK_PLAN_UNAVAILABLE",
        risk_plan_detail="index candles unavailable",
    )
    service = _service(db, settings)

    _opened, _skipped, _scored, errors = service.process_new_signals(
        trading_date=trading_date, lots=1, queue_only=True
    )

    assert errors == []
    states = _states(db, "RBV2-OUTAGE")
    assert "RED_BAR_V2_RISK_PLAN_REJECTED" not in states
    assert "QUEUED" in states


def test_an_unstamped_signal_is_not_blocked_on_absent_evidence(tmp_path):
    """A row published before the column existed carries NULL, and is left alone.

    The alternative -- treating NULL as untradable -- would have retired every
    signal already in the database the moment this gate shipped.
    """
    now = datetime.now(IST)
    trading_date = now.date().isoformat()
    settings, db = _setup(tmp_path)
    _insert_signal(
        db,
        signal_id="RBV2-UNSTAMPED",
        trading_date=trading_date,
        confirmation_timestamp=(now - timedelta(seconds=30)).isoformat(),
    )
    service = _service(db, settings)

    _opened, _skipped, _scored, errors = service.process_new_signals(
        trading_date=trading_date, lots=1, queue_only=True
    )

    assert errors == []
    states = _states(db, "RBV2-UNSTAMPED")
    assert "RED_BAR_V2_RISK_PLAN_REJECTED" not in states
    assert "QUEUED" in states
