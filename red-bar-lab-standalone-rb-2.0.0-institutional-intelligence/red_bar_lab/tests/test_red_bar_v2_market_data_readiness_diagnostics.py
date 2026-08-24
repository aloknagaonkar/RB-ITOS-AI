from datetime import date, datetime, timedelta, timezone

import pytest

from red_bar_lab.domain.red_bar_v2 import OptionSide
from red_bar_lab.services.red_bar_v2_canonical.paper_market_data import (
    PaperMarketDataCorruptionError,
    PaperMarketDataUnavailableError,
    PaperMarketQuote,
    PaperOptionInstrument,
    PaperUnderlyingQuote,
)
from red_bar_lab.services.red_bar_v2_canonical.paper_market_data_readiness import (
    PaperMarketDataReadinessService,
)
from red_bar_lab.services.red_bar_v2_canonical.paper_market_data_readiness_models import (
    MarketDataReadinessDiagnostic,
    MarketDataReadinessPolicy,
    MarketDataReadinessStage,
    MarketDataReadinessStatus,
)
from red_bar_lab.services.red_bar_v2_canonical.paper_market_data_readiness_store import (
    AtomicJsonMarketDataReadinessStore,
)

NOW = datetime(2026, 8, 24, 4, 0, tzinfo=timezone.utc)
EXPIRY = date(2026, 8, 27)


class Clock:
    def now(self): return NOW


class Provider:
    provider_name = "UPSTOX"
    def __init__(self, *, spot_error=None, spot_identity=True, contract_error=None, duplicate=False, stale=False, future=False):
        self.spot_error = spot_error; self.spot_identity = spot_identity
        self.contract_error = contract_error; self.duplicate = duplicate
        self.stale = stale; self.future = future
    def underlying_quote(self, *, underlying, evaluated_at):
        if self.spot_error: raise self.spot_error
        return PaperUnderlyingQuote("NSE_INDEX|Nifty 50", underlying if self.spot_identity else "OTHER", 24250.0, NOW, self.provider_name)
    def option_instruments(self, *, underlying, evaluated_at):
        if self.contract_error: raise self.contract_error
        rows = []
        for strike in range(23950, 24600, 50):
            for side in (OptionSide.CE, OptionSide.PE):
                token = strike * 10 + (1 if side is OptionSide.CE else 2)
                rows.append(PaperOptionInstrument(f"NSE_FO|{token}", token, f"NIFTY{strike}{side.value}", underlying, EXPIRY, float(strike), side, 75, self.provider_name))
        if self.duplicate:
            rows.append(PaperOptionInstrument("NSE_FO|999999", 999999, "DUPLICATE", underlying, EXPIRY, 24250.0, OptionSide.CE, 75, self.provider_name))
        return tuple(rows)
    def quotes(self, *, instrument_keys, evaluated_at):
        timestamp = NOW
        if self.stale: timestamp = NOW - timedelta(minutes=5)
        if self.future: timestamp = NOW + timedelta(minutes=5)
        return tuple(PaperMarketQuote(key, int(key.split("|")[-1]), 100.0, 99.0, 101.0, timestamp, self.provider_name) for key in instrument_keys)


def evaluate(provider):
    return PaperMarketDataReadinessService(market_data=provider, policy=MarketDataReadinessPolicy(), clock=Clock()).evaluate(underlying="NIFTY 50")


def test_spot_collection_and_validation_stages():
    report = evaluate(Provider(spot_error=PaperMarketDataUnavailableError("secret-token-value")))
    assert report.status is MarketDataReadinessStatus.SPOT_UNAVAILABLE
    assert report.failure_stage is MarketDataReadinessStage.UNDERLYING_QUOTE_COLLECTION
    assert report.reason_code == "UNDERLYING_QUOTE_UNAVAILABLE"
    report = evaluate(Provider(spot_identity=False))
    assert report.failure_stage is MarketDataReadinessStage.UNDERLYING_QUOTE_VALIDATION
    assert report.reason_code == "UNDERLYING_IDENTITY_MISMATCH"


def test_real_failure_shape_maps_to_contract_normalization_without_raw_text():
    report = evaluate(Provider(contract_error=PaperMarketDataCorruptionError("raw-payload Bearer secret-token-value")))
    assert report.status is MarketDataReadinessStatus.DATA_CORRUPT
    assert report.failure_stage is MarketDataReadinessStage.OPTION_CONTRACT_NORMALIZATION
    assert report.reason_code == "OPTION_CONTRACT_RESPONSE_MALFORMED"
    assert report.diagnostic is not None
    assert report.diagnostic.rejected_field == "response_shape"
    assert "secret" not in str(report).lower()
    assert "bearer" not in str(report).lower()


def test_duplicate_option_cell_is_precise_and_sanitized():
    report = evaluate(Provider(duplicate=True))
    assert report.status is MarketDataReadinessStatus.DATA_CORRUPT
    assert report.failure_stage is MarketDataReadinessStage.OPTION_CONTRACT_NORMALIZATION
    assert report.reason_code == "DUPLICATE_OPTION_CELL"
    assert report.diagnostic.rejected_field == "duplicate_identity"


def test_stale_and_future_quotes_have_distinct_stages():
    stale = evaluate(Provider(stale=True))
    assert stale.status is MarketDataReadinessStatus.QUOTES_STALE
    assert stale.failure_stage is MarketDataReadinessStage.QUOTE_FRESHNESS_VALIDATION
    assert stale.reason_code == "OPTION_QUOTE_STALE"
    future = evaluate(Provider(future=True))
    assert future.status is MarketDataReadinessStatus.DATA_CORRUPT
    assert future.failure_stage is MarketDataReadinessStage.QUOTE_FRESHNESS_VALIDATION
    assert future.reason_code == "OPTION_QUOTE_TIMESTAMP_INVALID"


def test_ready_report_uses_completed_without_diagnostic():
    report = evaluate(Provider())
    assert report.status is MarketDataReadinessStatus.READY
    assert report.failure_stage is MarketDataReadinessStage.COMPLETED
    assert report.diagnostic is None


def test_diagnostic_rejects_unsafe_content_and_types():
    with pytest.raises(ValueError):
        MarketDataReadinessDiagnostic(reason_code="OPTION_CONTRACT_REQUEST_FAILED", source_component="https://unsafe")
    with pytest.raises(ValueError):
        MarketDataReadinessDiagnostic(reason_code="OPTION_CONTRACT_REQUEST_FAILED", source_component="x", received_count=True)
    with pytest.raises(ValueError):
        MarketDataReadinessDiagnostic(reason_code="OPTION_CONTRACT_REQUEST_FAILED", source_component="x", rejected_field="raw_payload")


def test_persisted_diagnostic_contains_no_raw_failure_values(tmp_path):
    report = evaluate(Provider(contract_error=PaperMarketDataCorruptionError("Bearer secret-token raw-payload")))
    path = tmp_path / "readiness.json"
    store = AtomicJsonMarketDataReadinessStore(path)
    store.save(report)
    restored = store.load()
    assert restored == report
    text = path.read_text(encoding="utf-8").lower()
    assert "bearer" not in text and "secret-token" not in text and "raw-payload" not in text
