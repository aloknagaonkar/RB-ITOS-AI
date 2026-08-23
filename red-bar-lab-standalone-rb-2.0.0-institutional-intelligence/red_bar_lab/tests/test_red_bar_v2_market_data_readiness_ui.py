from dataclasses import replace

from red_bar_lab.config import RedBarSettings
from red_bar_lab.ui.canonical_market_data_readiness_panel import (
    render_canonical_market_data_readiness_panel,
)


class FakeStreamlit:
    def __init__(self): self.messages = []
    def markdown(self, value): self.messages.append(value)
    def warning(self, value): self.messages.append(value)
    def metric(self, *args): self.messages.append(str(args))
    def info(self, value): self.messages.append(value)
    def error(self, value): self.messages.append(value)
    def dataframe(self, *args, **kwargs): self.messages.append("dataframe")


def test_disabled_ui_reads_no_provider_and_shows_explicit_state(tmp_path):
    settings = replace(RedBarSettings(), artifacts_root=tmp_path)
    st = FakeStreamlit()
    render_canonical_market_data_readiness_panel(st, settings)
    assert any("READINESS_DISABLED" in value for value in st.messages)
    assert not settings.market_data_readiness_state_path.exists()
