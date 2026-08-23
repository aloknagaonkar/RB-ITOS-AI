from datetime import date, datetime, timezone
import json

import pytest

from red_bar_lab.services.red_bar_v2_canonical.paper_market_data_readiness_models import (
    MarketDataReadinessReport,
    MarketDataReadinessStatus,
    build_probe_id,
)
from red_bar_lab.services.red_bar_v2_canonical.paper_market_data_readiness_store import (
    AtomicJsonMarketDataReadinessStore,
    ReadinessStateCorruptionError,
    ReadinessStatePersistenceError,
)

NOW = datetime(2026, 8, 24, 4, 0, tzinfo=timezone.utc)


def report():
    return MarketDataReadinessReport(
        probe_id=build_probe_id(provider="UPSTOX", underlying="NIFTY 50", evaluated_at=NOW, expiry=None, atm_strike=None),
        provider="UPSTOX", underlying="NIFTY 50", underlying_instrument_key=None,
        evaluated_at=NOW, spot_price=None, spot_timestamp=None, expiry=None,
        strike_interval=None, atm_strike=None, expected_contract_count=0,
        observed_contract_count=0, ready_contract_count=0, ce_coverage=0, pe_coverage=0,
        status=MarketDataReadinessStatus.PROVIDER_UNAVAILABLE,
        reason_code="PROVIDER_UNAVAILABLE", contracts=(),
    )


def test_store_round_trip_and_digest_tampering(tmp_path):
    path = tmp_path / "readiness.json"; store = AtomicJsonMarketDataReadinessStore(path)
    original = report(); store.save(original); assert store.load() == original
    envelope = json.loads(path.read_text())
    envelope["payload"]["reason_code"] = "TAMPERED"
    path.write_text(json.dumps(envelope), encoding="utf-8")
    with pytest.raises(ReadinessStateCorruptionError): store.load()


def test_store_persistence_failure_is_typed(tmp_path, monkeypatch):
    store = AtomicJsonMarketDataReadinessStore(tmp_path / "missing" / "readiness.json")
    monkeypatch.setattr("os.replace", lambda *args: (_ for _ in ()).throw(OSError("no")))
    with pytest.raises(ReadinessStatePersistenceError): store.save(report())
