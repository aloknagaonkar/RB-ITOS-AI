from datetime import date

import pandas as pd

from red_bar_lab.config import RedBarSettings
from red_bar_lab.services.historical_service import RedBarHistoricalService
from red_bar_lab.services.historical_option_sync import HistoricalOptionChainSyncService
from red_bar_lab.services.replay_diagnostics import ReplayDiagnosticsService
from red_bar_lab.storage.artifacts import ArtifactLayout
from red_bar_lab.storage.database import RedBarDatabase


class CacheOnly:
    def historical_candles(self, *a, **k):
        raise AssertionError

    def intraday_candles(self, *a, **k):
        raise AssertionError


class DiagnosticProvider:
    def expired_option_expiries(self, instrument_key):
        return ["2026-08-06", "2026-08-13"]

    def expired_option_contracts(self, instrument_key, expiry):
        return [
            {"instrument_key": "NSE_FO|24500CE", "trading_symbol": "NIFTY 24500 CE", "instrument_type": "CE", "strike_price": 24500},
            {"instrument_key": "NSE_FO|24500PE", "trading_symbol": "NIFTY 24500 PE", "instrument_type": "PE", "strike_price": 24500},
        ]


def _setup(tmp_path):
    settings = RedBarSettings(artifacts_root=tmp_path / "red_bar")
    layout = ArtifactLayout(settings)
    layout.ensure()
    db = RedBarDatabase(settings.database_path)
    db.initialize()
    hist = RedBarHistoricalService(CacheOnly(), layout)
    day = date(2026, 8, 5)
    instrument = "NSE_INDEX|Nifty 50"
    ts = pd.date_range("2026-08-05 09:15", periods=3, freq="1min", tz="Asia/Kolkata")
    frame = pd.DataFrame({
        "timestamp": ts,
        "open": [100, 101, 102], "high": [101, 102, 103],
        "low": [99, 100, 101], "close": [100.5, 101.5, 102.5],
        "volume": [1000, 1200, 1500],
    })
    candle_path = layout.candle_path("upstox", instrument, 1, day.isoformat())
    candle_path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(candle_path, index=False)
    return settings, layout, db, hist, instrument, day


def test_rb152a_diagnostics_explains_zero_manifest_with_provider_discovery(tmp_path):
    settings, layout, db, hist, instrument, day = _setup(tmp_path)
    sync = HistoricalOptionChainSyncService(DiagnosticProvider(), layout, hist, database=db)
    report = ReplayDiagnosticsService(sync, hist, database=db).inspect_day(instrument, day)

    assert report.underlying_rows == 3
    assert report.resolved_expiry == "2026-08-06"
    assert report.expired_expiries_found == 2
    assert report.provider_contracts_found == 2
    assert report.stored_manifest_contracts == 0
    assert report.replay_ready is False
    stages = {row.stage: row for row in report.stages}
    assert stages["Underlying Data"].status == "PASS"
    assert stages["Stored Option Manifest"].status == "WARN"
    assert stages["Expiry Resolution"].status == "PASS"
    assert stages["Option Contract Discovery"].status == "PASS"
    assert stages["Replay Readiness"].status == "FAIL"
    assert report.database_status == "PASS"


def test_rb152a_diagnostics_reports_missing_expiry_as_first_discovery_failure(tmp_path):
    settings, layout, db, hist, instrument, day = _setup(tmp_path)

    class NoExpiry(DiagnosticProvider):
        def expired_option_expiries(self, instrument_key):
            return []

    sync = HistoricalOptionChainSyncService(NoExpiry(), layout, hist, database=db)
    report = ReplayDiagnosticsService(sync, hist, database=db).inspect_day(instrument, day)
    stages = {row.stage: row for row in report.stages}
    assert stages["Expired Expiry Discovery"].status == "FAIL"
    assert stages["Expiry Resolution"].status == "FAIL"
    assert stages["Option Contract Discovery"].status == "BLOCKED"
    assert report.replay_ready is False


def test_rb152b_expiry_resolution_normalizes_provider_formats(tmp_path):
    settings, layout, db, hist, instrument, day = _setup(tmp_path)

    class MixedFormatProvider(DiagnosticProvider):
        def expired_option_expiries(self, instrument_key):
            return ["04-08-2026", "11-08-2026", {"expiry": "2026-08-18"}, "bad-value"]

        def expired_option_contracts(self, instrument_key, expiry):
            assert expiry == "2026-08-11"
            return super().expired_option_contracts(instrument_key, expiry)

    sync = HistoricalOptionChainSyncService(MixedFormatProvider(), layout, hist, database=db)
    details = sync.expiry_resolution_details(instrument, day)
    assert details["selected"] == "2026-08-11"
    assert details["previous"] == "2026-08-04"
    assert details["next"] == "2026-08-11"
    assert details["parsed_count"] == 3
    assert details["unparsed_count"] == 1
    report = ReplayDiagnosticsService(sync, hist, database=db).inspect_day(instrument, day)
    assert report.resolved_expiry == "2026-08-11"
    assert report.expiry_previous == "2026-08-04"
    assert report.expiry_next == "2026-08-11"
    assert report.expiry_candidates[:2] == ("2026-08-11", "2026-08-18")


def test_rb152b_never_back_selects_expiry_before_trading_day(tmp_path):
    settings, layout, db, hist, instrument, day = _setup(tmp_path)

    class OnlyOldExpiries(DiagnosticProvider):
        def expired_option_expiries(self, instrument_key):
            return ["2026-07-28", "2026-08-04"]
        def expired_option_contracts(self, instrument_key, expiry):
            return []

    sync = HistoricalOptionChainSyncService(OnlyOldExpiries(), layout, hist, database=db)
    details = sync.expiry_resolution_details(instrument, day)
    assert details["selected"] is None
    assert details["previous"] == "2026-08-04"
    assert details["next"] is None


def test_rb152c_provider_probe_recovers_expiry_list_lag(tmp_path):
    settings, layout, db, hist, instrument, day = _setup(tmp_path)

    class LaggingExpiryListProvider(DiagnosticProvider):
        def __init__(self):
            self.contract_calls = []

        def expired_option_expiries(self, instrument_key):
            return ["2026-07-28", "2026-08-04"]

        def expired_option_contracts(self, instrument_key, expiry):
            self.contract_calls.append(expiry)
            if expiry == "2026-08-11":
                return super().expired_option_contracts(instrument_key, expiry)
            return []

    provider = LaggingExpiryListProvider()
    sync = HistoricalOptionChainSyncService(provider, layout, hist, database=db)
    details = sync.expiry_resolution_details(instrument, day)
    assert details["selected"] == "2026-08-11"
    assert details["resolution_source"] == "CONTRACT_ENDPOINT_PROBE"
    assert "2026-08-11" in details["probed_dates"]
    assert all(item >= day.isoformat() for item in details["probed_dates"])

    report = ReplayDiagnosticsService(sync, hist, database=db).inspect_day(instrument, day)
    assert report.resolved_expiry == "2026-08-11"
    assert report.expiry_resolution_source == "CONTRACT_ENDPOINT_PROBE"
    assert report.provider_contracts_found == 2


def test_rb152c_provider_probe_never_uses_previous_expiry(tmp_path):
    settings, layout, db, hist, instrument, day = _setup(tmp_path)

    class OldOnlyProvider(DiagnosticProvider):
        def __init__(self): self.calls = []
        def expired_option_expiries(self, instrument_key):
            return ["2026-07-28", "2026-08-04"]
        def expired_option_contracts(self, instrument_key, expiry):
            self.calls.append(expiry)
            return []

    provider = OldOnlyProvider()
    sync = HistoricalOptionChainSyncService(provider, layout, hist, database=db)
    details = sync.expiry_resolution_details(instrument, day)
    assert details["selected"] is None
    assert details["previous"] == "2026-08-04"
    assert provider.calls
    assert "2026-08-04" not in provider.calls
    assert all(item >= day.isoformat() for item in provider.calls)
