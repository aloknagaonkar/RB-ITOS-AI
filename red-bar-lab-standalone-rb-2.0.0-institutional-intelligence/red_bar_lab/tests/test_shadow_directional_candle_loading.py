from pathlib import Path


def test_shadow_page_loads_before_reading():
    page = Path(
        "red_bar_lab/ui/pages/shadow_directional_diagnostics.py"
    ).read_text(encoding="utf-8")

    helper_start = page.index("def _load_day(")
    helper_end = page.index("\n\ndef render_page", helper_start)
    helper = page[helper_start:helper_end]

    load_index = helper.index("historical.load_or_download(")
    read_index = helper.index("return historical.read_day(")

    assert load_index < read_index
    assert "interval_minutes=5" in helper
    assert "_load_day(historical, instrument_key, selected_date)" in page
    assert "_load_day(historical, instrument_key, replay_date)" in page
    assert "_load_day(historical, instrument_key, trading_day)" in page
