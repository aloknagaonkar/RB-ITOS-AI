from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from market_lab.domain import HistoricalPCRObservation, HistoricalPCRPanelResult
from market_lab.historical_evidence import (
    HistoricalEvidenceSessionSummary,
    build_historical_evidence_dataset,
    build_historical_evidence_rows,
)
from market_lab.historical_research import HistoricalResearchSession

IST = ZoneInfo("Asia/Kolkata")


def panel(mode, atm, pcr, call_pct=None, put_pct=None):
    return HistoricalPCRPanelResult(
        mode=mode,
        atm=atm,
        strikes=[] if atm is None else [atm],
        expected_contracts=2,
        received_oi_contracts=2 if pcr is not None else 0,
        call_oi=100 if pcr is not None else None,
        put_oi=int(100 * pcr) if pcr is not None else None,
        call_oi_change_pct=call_pct,
        put_oi_change_pct=put_pct,
        pcr=pcr,
        status="AVAILABLE" if pcr is not None else "UNAVAILABLE",
        issues=[] if pcr is not None else ["unavailable"],
    )


def observation(minute, spot, moving_pcr, fixed_pcr, full_pcr, moving_atm=23700, fixed_atm=23700):
    ts = datetime(2026, 9, 8, 9, 15, tzinfo=IST) + timedelta(minutes=minute)
    return HistoricalPCRObservation(
        timestamp=ts,
        session_date=date(2026, 9, 8),
        underlying="NSE_INDEX|Nifty 50",
        expiry=date(2026, 9, 8),
        spot=spot,
        moving_atm=moving_atm,
        strike_results=[],
        fixed_panel=panel("fixed", fixed_atm if fixed_pcr is not None else None, fixed_pcr, 1.0, 2.0),
        moving_panel=panel("moving", moving_atm, moving_pcr, 3.0, 4.0),
        full_reconstructed_panel=panel("full_reconstructed", None, full_pcr, 5.0, 6.0),
    )


def session(observations):
    return HistoricalResearchSession(
        status="AVAILABLE",
        underlying="NSE_INDEX|Nifty 50",
        session_date=date(2026, 9, 8),
        expiry=date(2026, 9, 8),
        wings=5,
        strike_interval=50,
        observations=observations,
        issues=[],
    )


def test_evidence_uses_exact_horizons_without_interpolation():
    rows = build_historical_evidence_rows(session([
        observation(0, 23680, 1.00, None, 1.10),
        observation(1, 23682, 1.02, None, 1.11),
        observation(5, 23690, 1.08, 0.97, 1.15),
        observation(10, 23710, 1.12, 1.01, 1.18, moving_atm=23700),
        observation(15, 23720, 1.20, 1.05, 1.25, moving_atm=23700),
        observation(35, 23780, 1.30, 1.10, 1.33, moving_atm=23800),
    ]))
    at_10 = next(row for row in rows if row.timestamp.minute == 25)
    assert at_10.moving_pcr_change_5m == 1.12 - 1.08
    assert at_10.moving_pcr_change_1m is None  # 09:24 is absent; no interpolation.
    assert at_10.forward_change_5m == 10
    assert at_10.forward_change_10m is None


def test_fixed_unavailable_before_anchor_and_atm_divergence_after_anchor():
    rows = build_historical_evidence_rows(session([
        observation(0, 23680, 1.00, None, 1.10),
        observation(5, 23690, 1.08, 0.97, 1.15),
        observation(6, 23730, 1.10, 0.98, 1.16, moving_atm=23750, fixed_atm=23700),
    ]))
    assert rows[0].fixed_pcr is None
    assert rows[0].fixed_atm is None
    assert rows[1].atm_divergence_points == 0
    assert rows[2].atm_divergence_points == 50
    assert abs(rows[2].fixed_moving_pcr_spread - 0.12) < 1e-12


def test_oi_change_percentages_are_exposed_fact_only():
    row = build_historical_evidence_rows(session([
        observation(5, 23690, 1.08, 0.97, 1.15),
    ]))[0]
    assert row.fixed_call_oi_change_pct == 1.0
    assert row.fixed_put_oi_change_pct == 2.0
    assert row.moving_call_oi_change_pct == 3.0
    assert row.full_put_oi_change_pct == 6.0


def test_dataset_keeps_unavailable_sessions_without_failing_available_data():
    good = session([observation(5, 23690, 1.08, 0.97, 1.15)])
    missing = HistoricalEvidenceSessionSummary(
        session_date=date(2026, 9, 9),
        expiry=date(2026, 9, 15),
        status="UNAVAILABLE",
        issues=["provider unavailable"],
    )
    dataset = build_historical_evidence_dataset("NSE_INDEX|Nifty 50", [good], [missing])
    assert dataset.status == "PARTIAL"
    assert dataset.requested_session_count == 2
    assert dataset.available_session_count == 1
    assert dataset.unavailable_session_count == 1
    assert dataset.row_count == 1


def test_exact_30_minute_pcr_and_forward_change():
    observations = [
        observation(5, 23690, 1.00, 0.90, 1.05),
        observation(35, 23740, 1.25, 1.10, 1.30),
        observation(65, 23710, 1.15, 1.00, 1.20),
    ]
    rows = build_historical_evidence_rows(session(observations))
    middle = rows[1]
    assert middle.moving_pcr_change_30m == 0.25
    assert abs(middle.fixed_pcr_change_30m - 0.20) < 1e-12
    assert middle.forward_change_30m == -30
