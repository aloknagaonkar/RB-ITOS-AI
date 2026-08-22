from datetime import datetime, timezone
import sqlite3
from types import SimpleNamespace

from red_bar_lab.services.authoritative_market_evidence import (
    apply_affirmative_derivatives_gate,
    completed_bar_timestamps,
)
from red_bar_lab.services.market_evidence_bundle_store import (
    persist_market_evidence_bundle,
    read_latest_market_evidence_bundle,
)
from red_bar_lab.ui.market_at_a_glance import build_market_at_a_glance
from red_bar_lab.ui import workspace_page_runtime
import red_bar_lab.ui.operations_readiness_wrapper as readiness_wrapper


def _underlying():
    return {
        "state": "BULLISH_STRUCTURE",
        "direction": "BULLISH",
        "acceptance_state": "HOLD_CONFIRMED",
        "rsi_view": "BULLISH_RECOVERY",
        "observed_at": "2026-08-21T10:15:00+00:00",
    }


def _summary(*, ce=45.0, pe=45.0):
    return {
        "ce_score": ce,
        "pe_score": pe,
        "ce_score_slope": 0.0,
        "pe_score_slope": 0.0,
        "eligible_ce": 2,
        "eligible_pe": 2,
        "observed_at": "2026-08-21T10:20:30+00:00",
    }


def _futures(*, state="NEUTRAL", strength="WEAK"):
    return {
        "positioning_state": state,
        "strength": strength,
        "observed_at": "2026-08-21T10:21:00+00:00",
        "latest_timestamp": "2026-08-21T10:20:00+00:00",
    }


def test_completed_bar_freshness_uses_explicit_close_timestamp():
    evidence = completed_bar_timestamps(_underlying())

    assert evidence["bar_open_timestamp"] == "2026-08-21T10:15:00+00:00"
    assert evidence["bar_close_timestamp"] == "2026-08-21T10:20:00+00:00"
    assert evidence["observed_at"] == "2026-08-21T10:15:00+00:00"

    view = build_market_at_a_glance(
        _summary(ce=60.0, pe=40.0),
        _futures(),
        _underlying(),
        now=datetime(2026, 8, 21, 10, 22, tzinfo=timezone.utc),
    )
    underlying_freshness = next(
        row for row in view["freshness_diagnostics"]
        if row["source"] == "Underlying candle"
    )
    assert underlying_freshness["age_seconds"] == 120.0
    assert underlying_freshness["status"] == "PASS"


def test_structure_without_positive_derivatives_confirmation_is_blocked():
    view = build_market_at_a_glance(
        _summary(),
        _futures(),
        _underlying(),
        now=datetime(2026, 8, 21, 10, 22, tzinfo=timezone.utc),
    )

    assert view["direction_state"] == "CONFIRMED"
    assert view["derivatives_confirmation_passed"] is False
    assert view["trade_eligibility"] == "BLOCKED"
    assert "DERIVATIVES_CONFIRMATION_MISSING" in view["blocking_reasons"]


def test_positive_option_confirmation_allows_eligibility_when_other_gates_pass():
    view = build_market_at_a_glance(
        _summary(ce=60.0, pe=40.0),
        _futures(),
        _underlying(),
        now=datetime(2026, 8, 21, 10, 22, tzinfo=timezone.utc),
    )

    assert view["derivatives_confirmation_passed"] is True
    assert view["derivatives_confirmations"] == ("OPTIONS",)
    assert view["trade_eligibility"] == "ELIGIBLE"
    assert view["trade_bias"] == "BUY CE"


def test_bundle_identity_keeps_later_source_snapshots_distinct(tmp_path):
    database_path = tmp_path / "evidence.db"
    base = {
        "as_of_timestamp": "2026-08-21T10:22:00+00:00",
        "underlying_bar_close_timestamp": "2026-08-21T10:20:00+00:00",
        "underlying_timestamp": "2026-08-21T10:20:00+00:00",
        "futures_market_timestamp": "2026-08-21T10:20:00+00:00",
        "futures_collection_timestamp": "2026-08-21T10:21:00+00:00",
        "option_timestamp": "2026-08-21T10:20:30+00:00",
        "observed_direction": "BULLISH",
        "direction_state": "CONFIRMED",
        "trade_eligibility": "ELIGIBLE",
    }
    first = persist_market_evidence_bundle(
        database_path, underlying_name="NIFTY 50", view=base
    )
    second_view = dict(base)
    second_view["as_of_timestamp"] = "2026-08-21T10:23:00+00:00"
    second_view["option_timestamp"] = "2026-08-21T10:22:30+00:00"
    second = persist_market_evidence_bundle(
        database_path, underlying_name="NIFTY 50", view=second_view
    )

    assert first != second
    with sqlite3.connect(database_path) as connection:
        count = connection.execute(
            "SELECT COUNT(*) FROM market_evidence_bundles"
        ).fetchone()[0]
    assert count == 2
    latest = read_latest_market_evidence_bundle(
        database_path, underlying_name="NIFTY 50"
    )
    assert latest["bundle_id"] == second


def test_operations_workspace_forces_read_only_default():
    original = readiness_wrapper.build_live_operations_readiness_view.__kwdefaults__
    fake_page = SimpleNamespace(render_page=lambda *args, **kwargs: None)
    try:
        workspace_page_runtime._configure_operations_center(fake_page)
        assert (
            readiness_wrapper.build_live_operations_readiness_view
            .__kwdefaults__["persist_outcomes"]
            is False
        )
    finally:
        readiness_wrapper.build_live_operations_readiness_view.__kwdefaults__ = original


def test_affirmative_gate_accepts_moderate_futures_agreement():
    result = apply_affirmative_derivatives_gate(
        {
            "observed_direction": "BEARISH",
            "direction_state": "CONFIRMED",
            "trade_eligibility": "ELIGIBLE",
            "trade_bias": "BUY PE",
            "blocking_reasons": (),
            "option_direction": "WAIT",
        },
        futures={"positioning_state": "SHORT_BUILDUP", "strength": "MODERATE"},
    )

    assert result["derivatives_confirmation_passed"] is True
    assert result["derivatives_confirmations"] == ("FUTURES",)
    assert result["trade_eligibility"] == "ELIGIBLE"
