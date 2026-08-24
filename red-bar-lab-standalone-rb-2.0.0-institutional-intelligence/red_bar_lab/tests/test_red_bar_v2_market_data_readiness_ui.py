from dataclasses import replace
from datetime import datetime, timezone

from red_bar_lab.config import RedBarSettings
from red_bar_lab.services.red_bar_v2_canonical.paper_market_data_readiness_models import (
    MarketDataReadinessDiagnostic,
    MarketDataReadinessReport,
    MarketDataReadinessStage,
    MarketDataReadinessStatus,
    build_probe_id,
)
from red_bar_lab.services.red_bar_v2_canonical.paper_market_data_readiness_store import (
    AtomicJsonMarketDataReadinessStore,
)
from red_bar_lab.ui.canonical_market_data_readiness_panel import (
    render_canonical_market_data_readiness_panel,
)

NOW = datetime(2026, 8, 24, 4, 0, tzinfo=timezone.utc)


class FakeStreamlit:
    def __init__(self): self.messages = []
    def markdown(self, value): self.messages.append(value)
    def warning(self, value): self.messages.append(value)
    def metric(self, *args): self.messages.append(str(args))
    def info(self, value): self.messages.append(value)
    def error(self, value): self.messages.append(value)
    def dataframe(self, frame, *args, **kwargs): self.messages.append(frame.to_string())


def test_disabled_ui_reads_no_provider_and_shows_explicit_state(tmp_path):
    settings = replace(RedBarSettings(), artifacts_root=tmp_path)
    st = FakeStreamlit()
    render_canonical_market_data_readiness_panel(st, settings)
    assert any("READINESS_DISABLED" in value for value in st.messages)
    assert not settings.market_data_readiness_state_path.exists()


def test_ui_renders_only_sanitized_diagnostic(tmp_path):
    settings = replace(
        RedBarSettings(),
        artifacts_root=tmp_path,
        red_bar_v2_market_data_readiness_enabled=True,
    )
    report = MarketDataReadinessReport(
        probe_id=build_probe_id(provider="UPSTOX", underlying="NIFTY 50", evaluated_at=NOW, expiry=None, atm_strike=None),
        provider="UPSTOX", underlying="NIFTY 50", underlying_instrument_key="NSE_INDEX|Nifty 50",
        evaluated_at=NOW, spot_price=24306.5, spot_timestamp=NOW, expiry=None,
        strike_interval=None, atm_strike=None, expected_contract_count=0,
        observed_contract_count=0, ready_contract_count=0, ce_coverage=0, pe_coverage=0,
        status=MarketDataReadinessStatus.DATA_CORRUPT,
        reason_code="OPTION_CONTRACT_RESPONSE_MALFORMED", contracts=(),
        failure_stage=MarketDataReadinessStage.OPTION_CONTRACT_NORMALIZATION,
        diagnostic=MarketDataReadinessDiagnostic(
            reason_code="OPTION_CONTRACT_RESPONSE_MALFORMED",
            source_component="option_contracts",
            received_count=1,
            normalized_count=0,
            rejected_count=1,
            rejected_field="response_shape",
            rejected_type="dict",
        ),
    )
    AtomicJsonMarketDataReadinessStore(settings.market_data_readiness_state_path).save(report)
    st = FakeStreamlit()
    render_canonical_market_data_readiness_panel(st, settings)
    output = "\n".join(st.messages)
    assert "OPTION_CONTRACT_NORMALIZATION" in output
    assert "OPTION_CONTRACT_RESPONSE_MALFORMED" in output
    assert "response_shape" in output
    assert "Bearer" not in output and "token" not in output.lower()
