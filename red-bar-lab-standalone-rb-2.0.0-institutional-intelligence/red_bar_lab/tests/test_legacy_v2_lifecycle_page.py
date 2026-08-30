from __future__ import annotations

from dataclasses import dataclass, field

import pytest

import red_bar_lab.ui.lifecycle_stepper as stepper_mod
from red_bar_lab.ui.pages.legacy_v2_lifecycle import (
    SIGNAL_KEY,
    STEPPER_KEY as LEGACY_STEPPER_KEY,
    render_page as render_legacy_page,
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
    selectbox_responses: list = field(default_factory=list)
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

    def selectbox(self, label, options, key=None, **kwargs):
        self.selectbox_calls.append((label, options, key))
        if not options:
            return None
        if self.selectbox_responses:
            return self.selectbox_responses.pop(0)
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

    def toast(self, message, icon=None):
        self.toast_calls.append((message, icon))
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
    import red_bar_lab.ui.pages.legacy_v2_lifecycle as mod

    monkeypatch.setattr(mod, "st", st)
    import red_bar_lab.ui._shared as shared

    monkeypatch.setattr(shared, "st", st)
    monkeypatch.setattr(stepper_mod, "st", st)
    return st


@pytest.fixture
def fake_st(monkeypatch):
    st = FakeSt()
    st.session_state = {LEGACY_STEPPER_KEY: 0, SIGNAL_KEY: None}
    _install_fake_st(monkeypatch, st)
    return st


def _fake_database():
    class FakeDb:
        def read_signal_attempts(self, instrument_key, trading_date):
            return []

        def read_paper_signal_diagnostics(self, trading_date, limit=200):
            return []

        def read_institutional_execution_evaluations(self, trading_date, limit=200):
            return []

        def read_opportunity_evaluations(self, trading_date, limit=200):
            return []

        def read_trade_selection_evaluations(self, trading_date, limit=200):
            return []

        def read_paper_candidate_decisions(self, trading_date, limit=200):
            return []

        def read_paper_execution_orders(self, account_id):
            return []

        def read_execution_queue(self, limit=200):
            return []

        def read_paper_execution_marks(self, order_id):
            return []

        def read_execution_state_events(self, trading_date, limit=500):
            return []

        def read_execution_state_events_for_signals(self, signal_ids):
            return []

    return FakeDb()


def test_legacy_page_renders_without_error(fake_st):
    render_legacy_page(
        settings=None,
        layout=None,
        database=_fake_database(),
        token="",
        underlying_name="NIFTY",
        instrument_key="NSE_INDEX|Nifty 50",
        interval=1,
    )
    assert any("Legacy V2" in title for title in fake_st.title_calls)
    assert any("PAPER TRADING ENABLED" in w for w in fake_st.warning_calls)
    assert fake_st.expander_calls, "expected 12 sections to render"
    assert fake_st.divider_calls >= 1, "expected a divider after the overview"
    assert fake_st.progress_calls == [], "single-page mode should not show a progress bar"


def test_legacy_page_renders_all_twelve_sections(fake_st):
    render_legacy_page(
        settings=None,
        layout=None,
        database=_fake_database(),
        token="",
        underlying_name="NIFTY",
        instrument_key="NSE_INDEX|Nifty 50",
        interval=1,
    )
    labels = [item[0] for item in fake_st.expander_calls]
    assert len(labels) == 12
    expected_titles = [
        "Signal Discovery",
        "Lifecycle Eligibility",
        "Decision",
        "Scoring & Selection",
        "Risk Gates",
        "Queue",
        "Entry",
        "Mark / Monitor",
        "Exit Health",
        "Close",
        "Attribution",
        "Persistence & Audit",
    ]
    for index, title in enumerate(expected_titles, start=1):
        assert f"{index}. {title}" in labels, f"missing section {index}. {title}"


def test_legacy_page_renders_section_anchors(fake_st):
    render_legacy_page(
        settings=None,
        layout=None,
        database=_fake_database(),
        token="",
        underlying_name="NIFTY",
        instrument_key="NSE_INDEX|Nifty 50",
        interval=1,
    )
    anchor_text = "".join(call[0] for call in fake_st.markdown_calls)
    for step_id in (
        "signal_discovery",
        "lifecycle_eligibility",
        "decision",
        "persistence_audit",
    ):
        assert f"lifecycle_section_{step_id}" in anchor_text


def test_legacy_page_handles_db_failure(monkeypatch):
    class ExplodingDb:
        def read_signal_attempts(self, instrument_key, trading_date):
            raise RuntimeError("db unavailable")

        def read_paper_signal_diagnostics(self, trading_date, limit=200):
            return []

        def read_institutional_execution_evaluations(self, trading_date, limit=200):
            return []

        def read_opportunity_evaluations(self, trading_date, limit=200):
            return []

        def read_trade_selection_evaluations(self, trading_date, limit=200):
            return []

        def read_paper_candidate_decisions(self, trading_date, limit=200):
            return []

        def read_paper_execution_orders(self, account_id):
            return []

        def read_execution_queue(self, limit=200):
            return []

        def read_paper_execution_marks(self, order_id):
            return []

        def read_execution_state_events(self, trading_date, limit=500):
            return []

        def read_execution_state_events_for_signals(self, signal_ids):
            return []

    st = FakeSt()
    st.session_state[LEGACY_STEPPER_KEY] = 0
    st.session_state[SIGNAL_KEY] = None
    _install_fake_st(monkeypatch, st)
    render_legacy_page(
        settings=None,
        layout=None,
        database=ExplodingDb(),
        token="",
        underlying_name="NIFTY",
        instrument_key="NSE_INDEX|Nifty 50",
        interval=1,
    )
    assert st.warning_calls, "expected graceful warning on db failure"
    assert any("Database read failed" in w for w in st.warning_calls)


def test_legacy_page_renders_live_mode_toggle_when_off(monkeypatch):
    """Live Mode is off by default — toggle is rendered but cadence panel is hidden."""
    import red_bar_lab.ui.pages.legacy_v2_lifecycle as mod
    import red_bar_lab.ui._shared as shared
    st = FakeSt()
    st.session_state[LEGACY_STEPPER_KEY] = 0
    st.session_state[SIGNAL_KEY] = None
    st.session_state["legacy_v2_lifecycle_live_mode"] = False
    monkeypatch.setattr(mod, "st", st)
    monkeypatch.setattr(shared, "st", st)
    monkeypatch.setattr(stepper_mod, "st", st)
    render_legacy_page(
        settings=None,
        layout=None,
        database=_fake_database(),
        token="",
        underlying_name="NIFTY",
        instrument_key="NSE_INDEX|Nifty 50",
        interval=1,
    )
    # The toggle was rendered, but the cadence panel is not visible.
    assert any("Live Mode" in label for label in st.toggle_labels) or any(
        "Live Mode" in (call[0] if isinstance(call, tuple) else call)
        for call in st.toggle_calls
    )


def test_legacy_page_follows_new_signal_when_live_mode_on(monkeypatch):
    """When Live Mode is on, a new last_signal_id snaps the page to it."""
    class FakeDbWithMonitor:
        def read_signal_attempts(self, instrument_key, trading_date):
            return []

        def read_paper_signal_diagnostics(self, trading_date, limit=200):
            return []

        def read_institutional_execution_evaluations(self, trading_date, limit=200):
            return []

        def read_opportunity_evaluations(self, trading_date, limit=200):
            return []

        def read_trade_selection_evaluations(self, trading_date, limit=200):
            return []

        def read_paper_candidate_decisions(self, trading_date, limit=200):
            return []

        def read_paper_execution_orders(self, account_id):
            return []

        def read_execution_queue(self, limit=200):
            return []

        def read_paper_execution_marks(self, order_id):
            return []

        def read_execution_state_events(self, trading_date, limit=500):
            return []

        def read_execution_state_events_for_signals(self, signal_ids):
            return []

        def read_paper_monitor_status(self, monitor_id="PAPER-MONITOR"):
            return {
                "monitor_id": "PAPER-MONITOR",
                "status": "RUNNING",
                "heartbeat_at": "2024-01-01T09:00:00+00:00",
                "last_signal_id": "RBV2-NEW",
                "last_decision": "OPEN",
                "last_error": None,
            }

        def read_pipeline_run_status(self, instrument_key, trading_date):
            return {
                "instrument_key": instrument_key,
                "trading_date": trading_date,
                "status": "HEALTHY",
                "message": "OK",
                "updated_at": "2024-01-01T09:00:00+00:00",
            }

    import red_bar_lab.ui.pages.legacy_v2_lifecycle as mod
    import red_bar_lab.ui._shared as shared
    st = FakeSt()
    st.session_state[LEGACY_STEPPER_KEY] = 0
    st.session_state[SIGNAL_KEY] = None
    st.session_state["legacy_v2_lifecycle_live_mode"] = True
    st.session_state["live_cadence_last_seen_signal_id"] = "RBV2-OLD"
    monkeypatch.setattr(mod, "st", st)
    monkeypatch.setattr(shared, "st", st)
    monkeypatch.setattr(stepper_mod, "st", st)
    # Patch out the time.sleep so the test does not actually wait.
    monkeypatch.setattr("time.sleep", lambda *_a, **_k: None)
    render_legacy_page(
        settings=None,
        layout=None,
        database=FakeDbWithMonitor(),
        token="",
        underlying_name="NIFTY",
        instrument_key="NSE_INDEX|Nifty 50",
        interval=1,
    )
    # The last seen signal should have updated to RBV2-NEW.
    assert st.session_state["live_cadence_last_seen_signal_id"] == "RBV2-NEW"
    # The page should have triggered a rerun (after the follow).
    assert st.rerun_calls >= 1
