from datetime import date, timedelta
from types import SimpleNamespace
import sys

from red_bar_lab.ui.historical_red_bar_v2_windows import (
    build_red_bar_v2_window_wrapper,
)


def test_window_wrapper_renders_after_existing_research_page(monkeypatch):
    calls = []

    def original(*args):
        calls.append("original")
        return "done"

    def panel(**kwargs):
        calls.append("panel")

    monkeypatch.setattr(
        "red_bar_lab.ui.historical_red_bar_v2_windows._render_window_panel",
        panel,
    )
    wrapped = build_red_bar_v2_window_wrapper(original)
    result = wrapped(None, None, None, None, None, None, None)

    assert result == "done"
    assert calls == ["original", "panel"]


def test_latest_10_day_window_ends_on_selected_date():
    dates = tuple(date(2026, 7, 1) + timedelta(days=index) for index in range(30))
    end_date = dates[20]
    eligible = tuple(day for day in dates if day <= end_date)
    selected = eligible[-10:]

    assert len(selected) == 10
    assert selected[-1] == end_date
    assert selected[0] == dates[11]


def test_latest_20_day_window_remains_partial_when_cache_is_short():
    dates = tuple(date(2026, 8, 1) + timedelta(days=index) for index in range(12))
    selected = dates[-20:]

    assert len(selected) == 12
    assert selected == dates


def test_workspace_runtime_wires_red_bar_v2_window_wrapper():
    from pathlib import Path

    path = Path(__file__).parents[1] / "ui" / "workspace_page_runtime.py"
    text = path.read_text(encoding="utf-8")

    assert "build_red_bar_v2_window_wrapper" in text
    assert "research_lab.render_page = build_red_bar_v2_window_wrapper" in text
