from __future__ import annotations

from dataclasses import dataclass, field
from types import SimpleNamespace

import pytest

import red_bar_lab.ui.lifecycle_stepper as stepper_mod
from red_bar_lab.ui.pages.canonical_v2_lifecycle import (
    BUNDLE_KEY,
    STEPPER_KEY as CANONICAL_STEPPER_KEY,
    render_page as render_canonical_page,
)


@dataclass
class FakeSt:
    session_state: dict = field(default_factory=dict)
    subheader_calls: list = field(default_factory=list)
    title_calls: list = field(default_factory=list)
    caption_calls: list = field(default_factory=list)
    warning_calls: list = field(default_factory=list)
    error_calls: list = field(default_factory=list)
    info_calls: list = field(default_factory=list)
    success_calls: list = field(default_factory=list)
    progress_calls: list = field(default_factory=list)
    dataframes: list = field(default_factory=list)
    metrics: list = field(default_factory=list)
    button_calls: list = field(default_factory=list)
    rerun_calls: int = 0
    selectbox_calls: list = field(default_factory=list)
    text_input_responses: dict = field(default_factory=dict)
    text_input_calls: list = field(default_factory=list)
    date_input_response: str = "2024-01-01"
    columns_specs: list = field(default_factory=list)
    expanders: int = 0
    expander_calls: list = field(default_factory=list)
    markdown_calls: list = field(default_factory=list)
    divider_calls: int = 0
    query_params: dict = field(default_factory=dict)
    toggle_calls: list = field(default_factory=list)
    checkbox_calls: list = field(default_factory=list)
    toggle_labels: list = field(default_factory=list)
    toast_calls: list = field(default_factory=list)

    def title(self, text):
        self.title_calls.append(text)

    def subheader(self, text):
        self.subheader_calls.append(text)

    def caption(self, text):
        self.caption_calls.append(text)

    def warning(self, text):
        self.warning_calls.append(text)

    def error(self, text):
        self.error_calls.append(text)

    def info(self, text):
        self.info_calls.append(text)

    def success(self, text):
        self.success_calls.append(text)

    def progress(self, value, text=None):
        self.progress_calls.append((value, text))

    def dataframe(self, data, **kwargs):
        self.dataframes.append(kwargs.get("hide_index", False))
        return None

    def metric(self, label, value, **kwargs):
        self.metrics.append((label, value))

    def button(self, label, key=None, disabled=False, **kwargs):
        self.button_calls.append((label, key, disabled))
        return False

    def rerun(self):
        self.rerun_calls += 1

    def toggle(self, label, value=False, key=None, **kwargs):
        self.toggle_calls.append((label, value, key))
        self.toggle_labels.append(label)
        return value

    def checkbox(self, label, value=False, key=None, **kwargs):
        self.checkbox_calls.append((label, value, key))
        return value

    def toast(self, message, icon=None):
        self.toast_calls.append((message, icon))
        return None

    def selectbox(self, label, options, key=None, **kwargs):
        self.selectbox_calls.append((label, options, key))
        if not options:
            return None
        return options[0]

    def text_input(self, label, value="", key=None, **kwargs):
        self.text_input_calls.append((label, value, key))
        return self.text_input_responses.get(key, value)

    def date_input(self, label, value=None, key=None):
        return value

    def columns(self, spec):
        self.columns_specs.append(spec)
        if isinstance(spec, (list, tuple)) and not all(isinstance(item, int) for item in spec):
            n = len(spec)
        elif isinstance(spec, int):
            n = spec
        elif isinstance(spec, (list, tuple)):
            n = len(spec)
        else:
            n = 1
        return [_FakeColumn() for _ in range(n)]

    def markdown(self, text, **kwargs):
        self.markdown_calls.append((text, kwargs))
        return None

    def divider(self):
        self.divider_calls += 1
        return None

    def expander(self, label, expanded=False):
        self.expanders += 1
        self.expander_calls.append((label, expanded))

        class _Ctx:
            def __enter__(self_inner):
                return self_inner

            def __exit__(self_inner, *args):
                return False

        return _Ctx()

    def write(self, *_args, **_kwargs):
        return None


class _FakeColumn:
    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def metric(self, label, value):
        return None

    def caption(self, text):
        return None

    def button(self, *args, **kwargs):
        return False

    def date_input(self, label, value=None, key=None):
        return value

    def selectbox(self, label, options, key=None):
        return options[0] if options else None

    def text_input(self, label, value="", key=None, **kwargs):
        return value


def _install_fake_st(monkeypatch, st):
    import red_bar_lab.ui.pages.canonical_v2_lifecycle as mod

    monkeypatch.setattr(mod, "st", st)
    import red_bar_lab.ui._shared as shared

    monkeypatch.setattr(shared, "st", st)
    monkeypatch.setattr(stepper_mod, "st", st)
    return st


@pytest.fixture
def fake_st(monkeypatch):
    st = FakeSt()
    st.session_state = {CANONICAL_STEPPER_KEY: 0, BUNDLE_KEY: None}
    _install_fake_st(monkeypatch, st)
    return st


def _fake_settings():
    return SimpleNamespace(
        database_path="/tmp/canonical_v2.db",
        paper_canary_state_path="/tmp/canonical_canary.json",
        red_bar_v2_canonical_shadow_enabled=False,
        red_bar_v2_canonical_reservation_enabled=False,
        red_bar_v2_canonical_paper_execution_enabled=False,
        red_bar_v2_canonical_paper_execution_mode="OBSERVE_ONLY",
        red_bar_v2_paper_canary_worker_enabled=False,
        red_bar_v2_paper_canary_market_data_provider="UNCONFIGURED",
        red_bar_v2_paper_canary_max_actions_per_day=10,
        red_bar_v2_paper_canary_max_bundle_age_seconds=120.0,
        red_bar_v2_paper_canary_failure_threshold=3,
    )


def _fake_database():
    class FakeDb:
        def read_signal_attempts(self, instrument_key, trading_date):
            return []

    return FakeDb()


def test_canonical_page_renders_banner(fake_st):
    render_canonical_page(
        settings=_fake_settings(),
        layout=None,
        database=_fake_database(),
        token="",
        underlying_name="NIFTY",
        instrument_key="NSE_INDEX|Nifty 50",
        interval=1,
    )
    assert any("Canonical V2" in title for title in fake_st.title_calls)
    assert any("PAPER TRADING IS NOT YET ENABLED" in e for e in fake_st.error_calls)
    assert any("OBSERVE_ONLY" in e for e in fake_st.error_calls)


def test_canonical_page_renders_all_twelve_sections(fake_st):
    render_canonical_page(
        settings=_fake_settings(),
        layout=None,
        database=_fake_database(),
        token="",
        underlying_name="NIFTY",
        instrument_key="NSE_INDEX|Nifty 50",
        interval=1,
    )
    labels = [item[0] for item in fake_st.expander_calls]
    # Section labels are numbered (e.g. "1. Reference Readiness") — filter those.
    section_labels = [label for label in labels if label[:2].rstrip(".").isdigit()]
    assert len(section_labels) == 12
    expected_titles = [
        "Reference Readiness",
        "Decision",
        "Signal Bundle",
        "Architecture Parity",
        "Persistence & Integrity",
        "Recent Observations",
        "Opportunity Queue",
        "Reservation Boundary",
        "Paper Execution",
        "Paper Canary",
        "Process & Status",
        "Promotion Gates",
    ]
    for index, title in enumerate(expected_titles, start=1):
        assert f"{index}. {title}" in labels, f"missing section {index}. {title}"


def test_canonical_page_does_not_show_progress_bar(fake_st):
    render_canonical_page(
        settings=_fake_settings(),
        layout=None,
        database=_fake_database(),
        token="",
        underlying_name="NIFTY",
        instrument_key="NSE_INDEX|Nifty 50",
        interval=1,
    )
    assert fake_st.progress_calls == []


def test_canonical_page_renders_section_anchors(fake_st):
    render_canonical_page(
        settings=_fake_settings(),
        layout=None,
        database=_fake_database(),
        token="",
        underlying_name="NIFTY",
        instrument_key="NSE_INDEX|Nifty 50",
        interval=1,
    )
    anchor_text = "".join(call[0] for call in fake_st.markdown_calls)
    for step_id in ("signal_discovery", "mark_monitor", "persistence_audit"):
        assert f"lifecycle_section_{step_id}" in anchor_text
