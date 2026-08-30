from __future__ import annotations

from dataclasses import dataclass, field

import pytest

import red_bar_lab.ui.lifecycle_stepper as stepper_mod
from red_bar_lab.ui.lifecycle_stepper import (
    LifecycleContext,
    LifecycleStep,
    make_step,
    render_lifecycle,
    render_lifecycle_all,
    safe_read,
    signal_selector,
)


@dataclass
class FakeSt:
    progress_calls: list = field(default_factory=list)
    subheader_calls: list = field(default_factory=list)
    caption_calls: list = field(default_factory=list)
    error_calls: list = field(default_factory=list)
    info_calls: list = field(default_factory=list)
    warning_calls: list = field(default_factory=list)
    success_calls: list = field(default_factory=list)
    button_calls: list = field(default_factory=list)
    rerun_calls: int = 0
    selectbox_responses: list = field(default_factory=list)
    selectbox_calls: list = field(default_factory=list)
    session_state: dict = field(default_factory=dict)
    columns_specs: list = field(default_factory=list)
    markdown_calls: list = field(default_factory=list)
    divider_calls: int = 0
    expander_calls: list = field(default_factory=list)
    query_params: dict = field(default_factory=dict)

    def progress(self, value, text=None):
        self.progress_calls.append((value, text))

    def subheader(self, text):
        self.subheader_calls.append(text)

    def caption(self, text):
        self.caption_calls.append(text)

    def error(self, text):
        self.error_calls.append(text)

    def info(self, text):
        self.info_calls.append(text)

    def warning(self, text):
        self.warning_calls.append(text)

    def success(self, text):
        self.success_calls.append(text)

    def button(self, label, key=None, disabled=False, **kwargs):
        self.button_calls.append((label, key, disabled))
        return False

    def rerun(self):
        self.rerun_calls += 1

    def selectbox(self, label, options, key=None):
        self.selectbox_calls.append((label, options, key))
        if not options:
            return None
        if self.selectbox_responses:
            return self.selectbox_responses.pop(0)
        return options[0]

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
        self.expander_calls.append((label, expanded))

        class _Ctx:
            def __enter__(self_inner):
                return self_inner

            def __exit__(self_inner, *args):
                return False

        return _Ctx()


class _FakeColumn:
    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def button(self, *args, **kwargs):
        return False

    def caption(self, text):
        return None

    def date_input(self, label, value=None, key=None):
        return value

    def selectbox(self, label, options, key=None):
        return options[0] if options else None

    def text_input(self, label, value="", key=None, **kwargs):
        return value


@pytest.fixture
def fake_st(monkeypatch):
    """Replace the streamlit reference inside lifecycle_stepper with a fake."""
    st = FakeSt()
    st.session_state = {}
    monkeypatch.setattr(stepper_mod, "st", st)
    return st


def _context() -> LifecycleContext:
    return LifecycleContext(
        settings=None,
        layout=None,
        database=None,
        token="",
        underlying_name="NIFTY",
        instrument_key="NSE_INDEX|Nifty 50",
        interval=1,
        trading_date="2024-01-01",
        signal_id=None,
    )


def _two_steps() -> list[LifecycleStep]:
    def step_one(st, ctx):
        st.subheader_calls.append("rendered:one")

    def step_two(st, ctx):
        st.subheader_calls.append("rendered:two")

    return [
        make_step(step_id="one", title="One", description="first", renderer=step_one),
        make_step(step_id="two", title="Two", description="second", renderer=step_two),
    ]


def test_render_lifecycle_renders_current_step(fake_st):
    fake_st.session_state = {"stepper": 0}
    render_lifecycle(
        steps=_two_steps(),
        context=_context(),
        stepper_key="stepper",
    )
    assert fake_st.progress_calls == [(0.5, "Step 1 of 2")]
    assert "rendered:one" in fake_st.subheader_calls
    assert "rendered:two" not in fake_st.subheader_calls
    assert any("1. One" in text for text in fake_st.subheader_calls)


def test_render_lifecycle_clamps_index_to_bounds(fake_st):
    fake_st.session_state = {"stepper": 99}
    render_lifecycle(
        steps=_two_steps(),
        context=_context(),
        stepper_key="stepper",
    )
    assert fake_st.session_state["stepper"] == 1
    assert "rendered:two" in fake_st.subheader_calls


def test_render_lifecycle_handles_empty_steps(fake_st):
    render_lifecycle(steps=[], context=_context(), stepper_key="empty")
    assert fake_st.error_calls
    assert "no steps" in fake_st.error_calls[0].lower()


def test_render_lifecycle_isolates_step_exceptions(fake_st):
    def bad(st, ctx):
        raise RuntimeError("boom")

    steps = [
        make_step(step_id="bad", title="Bad", description="explodes", renderer=bad),
    ]
    fake_st.session_state = {"stepper": 0}
    render_lifecycle(steps=steps, context=_context(), stepper_key="stepper")
    assert any("boom" in message for message in fake_st.error_calls)


def test_safe_read_returns_default_on_exception():
    def boom():
        raise ValueError("nope")

    assert safe_read(boom, default="fallback") == "fallback"


def test_safe_read_returns_value_when_no_exception():
    assert safe_read(lambda: 42, default=0) == 42


def test_signal_selector_returns_none_when_no_rows(fake_st):
    class FakeDb:
        def read_signal_attempts(self, instrument_key, trading_date):
            return []

    selected = signal_selector(
        fake_st,
        FakeDb(),
        instrument_key="NSE_INDEX|Nifty 50",
        trading_date="2024-01-01",
        selectbox_key="signal",
    )
    assert selected is None


def test_signal_selector_returns_signal_id(fake_st):
    class FakeDb:
        def read_signal_attempts(self, instrument_key, trading_date):
            return [
                {
                    "signal_id": "RBV2-123",
                    "direction": "BULLISH",
                    "level_type": "RED_BAR_V2",
                    "confirmation_timestamp": "2024-01-01T09:30:00+05:30",
                }
            ]

    selected = signal_selector(
        fake_st,
        FakeDb(),
        instrument_key="NSE_INDEX|Nifty 50",
        trading_date="2024-01-01",
        selectbox_key="signal",
    )
    assert selected == "RBV2-123"


def test_render_lifecycle_progress_text_reflects_total(fake_st):
    fake_st.session_state = {"stepper": 0}
    render_lifecycle(
        steps=_two_steps(),
        context=_context(),
        stepper_key="stepper",
    )
    text = fake_st.progress_calls[0][1]
    assert "1 of 2" in text


def test_render_lifecycle_all_renders_every_step_in_order(fake_st):
    render_lifecycle_all(
        steps=_two_steps(),
        context=_context(),
        page_key="all_page",
    )
    assert "rendered:one" in fake_st.subheader_calls
    assert "rendered:two" in fake_st.subheader_calls
    assert fake_st.subheader_calls.index("rendered:one") < fake_st.subheader_calls.index(
        "rendered:two"
    )


def test_render_lifecycle_all_wraps_each_step_in_expander(fake_st):
    render_lifecycle_all(
        steps=_two_steps(),
        context=_context(),
        page_key="all_page",
    )
    labels = [item[0] for item in fake_st.expander_calls]
    assert "1. One" in labels
    assert "2. Two" in labels


def test_render_lifecycle_all_default_expands_sections(fake_st):
    render_lifecycle_all(
        steps=_two_steps(),
        context=_context(),
        page_key="all_page",
    )
    expanded_flags = [item[1] for item in fake_st.expander_calls]
    assert all(expanded_flags), "all sections should start expanded by default"


def test_render_lifecycle_all_respects_expander_default_closed(fake_st):
    render_lifecycle_all(
        steps=_two_steps(),
        context=_context(),
        page_key="all_page",
        expander_default="closed",
    )
    expanded_flags = [item[1] for item in fake_st.expander_calls]
    assert not any(expanded_flags), "all sections should start collapsed"


def test_render_lifecycle_all_does_not_render_progress_bar(fake_st):
    render_lifecycle_all(
        steps=_two_steps(),
        context=_context(),
        page_key="all_page",
    )
    assert fake_st.progress_calls == []


def test_render_lifecycle_all_renders_section_anchors_when_enabled(fake_st):
    render_lifecycle_all(
        steps=_two_steps(),
        context=_context(),
        page_key="all_page",
        show_anchors=True,
    )
    anchor_text = "".join(call[0] for call in fake_st.markdown_calls)
    assert "lifecycle_section_one" in anchor_text
    assert "lifecycle_section_two" in anchor_text


def test_render_lifecycle_all_omits_anchors_when_disabled(fake_st):
    render_lifecycle_all(
        steps=_two_steps(),
        context=_context(),
        page_key="all_page",
        show_anchors=False,
    )
    anchor_text = "".join(call[0] for call in fake_st.markdown_calls)
    assert "lifecycle_section_" not in anchor_text


def test_render_lifecycle_all_renders_jump_buttons(fake_st):
    render_lifecycle_all(
        steps=_two_steps(),
        context=_context(),
        page_key="all_page",
    )
    button_labels = [item[0] for item in fake_st.button_calls]
    assert any("1. One" in label for label in button_labels)
    assert any("2. Two" in label for label in button_labels)


def test_render_lifecycle_all_isolates_step_exceptions(fake_st):
    def bad(st, ctx):
        raise RuntimeError("kaboom")

    steps = [
        make_step(step_id="a", title="A", description="ok", renderer=lambda s, c: None),
        make_step(step_id="b", title="B", description="bad", renderer=bad),
        make_step(step_id="c", title="C", description="ok", renderer=lambda s, c: None),
    ]
    render_lifecycle_all(
        steps=steps,
        context=_context(),
        page_key="all_page",
    )
    assert any("kaboom" in message for message in fake_st.error_calls)


def test_render_lifecycle_all_handles_empty_steps(fake_st):
    render_lifecycle_all(
        steps=[],
        context=_context(),
        page_key="all_page",
    )
    assert fake_st.error_calls
    assert "no steps" in fake_st.error_calls[0].lower()


def test_render_lifecycle_all_invokes_banner_renderer(fake_st):
    banner_calls: list = []

    def banner(st, ctx):
        banner_calls.append("called")

    render_lifecycle_all(
        steps=_two_steps(),
        context=_context(),
        page_key="all_page",
        banner_renderer=banner,
    )
    assert banner_calls == ["called"]


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
