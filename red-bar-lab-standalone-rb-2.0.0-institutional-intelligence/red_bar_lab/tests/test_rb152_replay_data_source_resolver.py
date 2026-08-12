from datetime import date
from pathlib import Path

import pandas as pd

from red_bar_lab.config import RedBarSettings
from red_bar_lab.services.historical_service import RedBarHistoricalService
from red_bar_lab.services.historical_option_sync import HistoricalOptionChainSyncService
from red_bar_lab.storage.artifacts import ArtifactLayout
from red_bar_lab.storage.database import RedBarDatabase


class CacheOnly:
    def historical_candles(self, *a, **k):
        raise AssertionError

    def intraday_candles(self, *a, **k):
        raise AssertionError


class NoExpiredNetwork:
    def expired_option_expiries(self, *a, **k):
        raise AssertionError("live capture should be resolved without expired-option network calls")


def _underlying(day: str):
    ts = pd.date_range(f"{day} 09:15", periods=5, freq="1min", tz="Asia/Kolkata")
    return pd.DataFrame({
        "timestamp": ts,
        "open": [100, 101, 102, 103, 104],
        "high": [101, 102, 103, 104, 105],
        "low": [99, 100, 101, 102, 103],
        "close": [100.5, 101.5, 102.5, 103.5, 104.5],
        "volume": [100000] * 5,
    })


def _chain(step: int):
    rows = []
    for strike in (100.0, 105.0):
        rows.append({
            "expiry": "2026-08-13",
            "spot": 103.0 + step,
            "strike": strike,
            "call_instrument_key": f"NSE_FO|{int(strike)}CE",
            "call_ltp": 20.0 + step + strike / 100.0,
            "call_volume": 70000 + step,
            "call_oi": 150000 + step,
            "call_bid": 20.0 + step,
            "call_bid_qty": 500,
            "call_ask": 20.1 + step,
            "call_ask_qty": 550,
            "call_iv": 14.0,
            "call_delta": 0.5,
            "call_gamma": 0.02,
            "call_theta": -2.0,
            "call_vega": 4.0,
            "put_instrument_key": f"NSE_FO|{int(strike)}PE",
            "put_ltp": 18.0 + step + strike / 100.0,
            "put_volume": 80000 + step,
            "put_oi": 160000 + step,
            "put_bid": 18.0 + step,
            "put_bid_qty": 600,
            "put_ask": 18.1 + step,
            "put_ask_qty": 650,
            "put_iv": 15.0,
            "put_delta": -0.5,
            "put_gamma": 0.02,
            "put_theta": -2.1,
            "put_vega": 4.1,
        })
    return pd.DataFrame(rows)


def _setup(tmp_path):
    settings = RedBarSettings(artifacts_root=tmp_path / "red_bar")
    layout = ArtifactLayout(settings)
    layout.ensure()
    db = RedBarDatabase(settings.database_path)
    db.initialize()
    hist = RedBarHistoricalService(CacheOnly(), layout)
    day = date(2026, 8, 11)
    instrument = "NSE_INDEX|Nifty 50"
    candle_path = layout.candle_path("upstox", instrument, 1, day.isoformat())
    candle_path.parent.mkdir(parents=True, exist_ok=True)
    _underlying(day.isoformat()).to_csv(candle_path, index=False)

    for step, ts in enumerate(pd.date_range("2026-08-11 09:15", periods=5, freq="1min", tz="Asia/Kolkata")):
        chain_path = settings.artifacts_root / "options" / "history" / "test" / day.isoformat() / f"online_{step}.csv"
        chain_path.parent.mkdir(parents=True, exist_ok=True)
        _chain(step).to_csv(chain_path, index=False)
        db.upsert_option_chain_history({
            "snapshot_key": f"snap-{step}",
            "instrument_key": instrument,
            "trading_date": day.isoformat(),
            "option_expiry": "2026-08-13",
            "snapshot_timestamp": ts.isoformat(),
            "collector_mode": "ONLINE",
            "option_spot_price": 103.0 + step,
            "chain_artifact_path": str(chain_path),
        })
    return instrument, day, layout, db, hist


def test_rb152_prefers_same_day_live_market_capture(tmp_path):
    instrument, day, layout, db, hist = _setup(tmp_path)
    sync = HistoricalOptionChainSyncService(NoExpiredNetwork(), layout, hist, database=db)
    report = sync.validate_day(instrument, day)
    assert report.replay_ready is True
    assert report.data_source == "LIVE_MARKET_CAPTURE"
    assert report.fidelity == "LIVE_CAPTURE_PARITY_HIGH"
    assert report.live_snapshots == 5
    assert report.snapshot_coverage_pct == 100.0
    assert report.bid_ask_available is True
    assert report.iv_available is True
    assert report.greeks_available is True


def test_rb152_live_capture_point_in_time_excludes_future_snapshots(tmp_path):
    instrument, day, layout, db, hist = _setup(tmp_path)
    sync = HistoricalOptionChainSyncService(NoExpiredNetwork(), layout, hist, database=db)
    contracts = sync.point_in_time_contracts(instrument, day, pd.Timestamp("2026-08-11 09:17", tz="Asia/Kolkata"))
    assert contracts
    # Three captured minutes are available at 09:17: 09:15, 09:16 and 09:17.
    assert all(len(frame) == 3 for _, frame in contracts)
    assert all(pd.to_datetime(frame["timestamp"], utc=True).max() <= pd.Timestamp("2026-08-11 09:17", tz="Asia/Kolkata").tz_convert("UTC") for _, frame in contracts)
    assert any(float(frame.iloc[-1]["best_bid"]) > 0 for _, frame in contracts)
