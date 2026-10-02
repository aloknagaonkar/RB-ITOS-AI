from pathlib import Path


ROOT = Path(__file__).parents[1]


def test_hilega_page_contains_live_historical_workspace_selector():
    source = (ROOT / "frontend/src/hilegaMilegaShadow.tsx").read_text(encoding="utf-8")
    assert "import HilegaHistoricalReplay" in source
    assert "Live shadow" in source
    assert "Historical replay" in source
    assert "<HilegaHistoricalReplay/>" in source


def test_historical_selection_loads_without_second_click():
    source = (ROOT / "frontend/src/hilegaHistoricalReplay.tsx").read_text(encoding="utf-8")
    assert "if(selectedDate)void load()" in source
    assert "Reload session" in source
