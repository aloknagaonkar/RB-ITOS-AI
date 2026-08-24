from __future__ import annotations

from types import SimpleNamespace

from red_bar_lab.ui import workspace_page_runtime
from red_bar_lab.ui.pages import red_bar_v2_validation


def test_workspace_is_registered_in_sidebar_navigation():
    assert (
        workspace_page_runtime.PAGE_MODULE_PATHS["Red Bar V2 Validation"]
        == "red_bar_lab.ui.pages.red_bar_v2_validation"
    )


def test_workspace_page_renders_windows_before_promotion(monkeypatch):
    calls = []

    class StreamlitStub:
        def subheader(self, value):
            calls.append(("subheader", value))

        def caption(self, value):
            calls.append(("caption", value))

        def divider(self):
            calls.append(("divider", None))

        def columns(self, count):
            return tuple(SimpleNamespace(metric=lambda *args, **kwargs: None) for _ in range(count))

        class _Expander:
            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

        def expander(self, *args, **kwargs):
            return self._Expander()

        def markdown(self, value):
            calls.append(("markdown", value))

        def info(self, value):
            calls.append(("info", value))

    stub = StreamlitStub()
    monkeypatch.setattr(red_bar_v2_validation, "st", stub)
    monkeypatch.setattr(
        red_bar_v2_validation,
        "_render_shadow_observability",
        lambda settings, instrument_key: calls.append(("observability", instrument_key)),
    )
    monkeypatch.setattr(
        red_bar_v2_validation,
        "_render_window_panel",
        lambda **kwargs: calls.append(("windows", kwargs["instrument_key"])),
    )
    monkeypatch.setattr(
        red_bar_v2_validation,
        "render_red_bar_v2_promotion_panel",
        lambda st, settings: calls.append(("promotion", settings)),
    )

    settings = SimpleNamespace()
    red_bar_v2_validation.render_page(
        settings,
        SimpleNamespace(),
        SimpleNamespace(),
        "token",
        "NIFTY 50",
        "NSE_INDEX|Nifty 50",
        1,
    )

    window_index = next(i for i, item in enumerate(calls) if item[0] == "windows")
    promotion_index = next(i for i, item in enumerate(calls) if item[0] == "promotion")
    assert window_index < promotion_index


def test_workspace_module_loads_through_runtime():
    module = workspace_page_runtime.load_page_module("Red Bar V2 Validation")
    assert module.__name__ == "red_bar_lab.ui.pages.red_bar_v2_validation"
    assert callable(module.render_page)
