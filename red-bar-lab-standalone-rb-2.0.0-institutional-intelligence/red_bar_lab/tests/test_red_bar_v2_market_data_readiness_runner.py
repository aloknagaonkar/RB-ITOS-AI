from dataclasses import replace
from datetime import datetime, timezone

from red_bar_lab.config import RedBarSettings
from red_bar_lab.execution import run_red_bar_v2_market_data_readiness as runner
from red_bar_lab.services.red_bar_v2_canonical.paper_market_data_readiness_models import (
    MarketDataReadinessReport,
    MarketDataReadinessStatus,
    build_probe_id,
)

NOW = datetime(2026, 8, 24, 4, 0, tzinfo=timezone.utc)


def _report():
    return MarketDataReadinessReport(
        probe_id=build_probe_id(provider="UPSTOX", underlying="NIFTY 50", evaluated_at=NOW, expiry=None, atm_strike=None),
        provider="UPSTOX", underlying="NIFTY 50", underlying_instrument_key=None,
        evaluated_at=NOW, spot_price=None, spot_timestamp=None, expiry=None,
        strike_interval=None, atm_strike=None, expected_contract_count=0,
        observed_contract_count=0, ready_contract_count=0, ce_coverage=0, pe_coverage=0,
        status=MarketDataReadinessStatus.PROVIDER_UNAVAILABLE,
        reason_code="PROVIDER_UNAVAILABLE", contracts=(),
    )


def test_disabled_runner_performs_no_provider_construction(monkeypatch, capsys):
    monkeypatch.setattr(runner.RedBarSettings, "from_env", classmethod(lambda cls: RedBarSettings()))
    monkeypatch.setattr(runner, "build_paper_canary_market_data", lambda **kwargs: (_ for _ in ()).throw(AssertionError("provider built")))
    assert runner.main([]) == 0
    assert "READINESS_DISABLED" in capsys.readouterr().out


def test_invalid_provider_does_not_build_provider(monkeypatch):
    settings = replace(RedBarSettings(), red_bar_v2_market_data_readiness_enabled=True, red_bar_v2_market_data_readiness_provider="INVALID")
    monkeypatch.setattr(runner.RedBarSettings, "from_env", classmethod(lambda cls: settings))
    monkeypatch.setattr(runner, "build_paper_canary_market_data", lambda **kwargs: (_ for _ in ()).throw(AssertionError("provider built")))
    assert runner.main([]) == 2


def test_enabled_runner_evaluates_once_and_persists(monkeypatch, tmp_path):
    settings = replace(RedBarSettings(), artifacts_root=tmp_path, red_bar_v2_market_data_readiness_enabled=True, red_bar_v2_market_data_readiness_provider="UPSTOX")
    calls = {"factory": 0, "evaluate": 0}
    monkeypatch.setattr(runner.RedBarSettings, "from_env", classmethod(lambda cls: settings))
    monkeypatch.setattr(runner, "build_paper_canary_market_data", lambda **kwargs: calls.__setitem__("factory", calls["factory"] + 1) or object())
    class Service:
        def __init__(self, **kwargs): pass
        def evaluate(self, **kwargs): calls["evaluate"] += 1; return _report()
    monkeypatch.setattr(runner, "PaperMarketDataReadinessService", Service)
    assert runner.main([]) == 5
    assert calls == {"factory": 1, "evaluate": 1}
    assert settings.market_data_readiness_state_path.exists()
