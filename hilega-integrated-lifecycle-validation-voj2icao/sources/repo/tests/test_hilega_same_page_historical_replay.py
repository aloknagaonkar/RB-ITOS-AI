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


def test_frontend_api_proxy_targets_runtime_api_port():
    source = (ROOT / "frontend/vite.config.ts").read_text(encoding="utf-8")
    assert "'/api': 'http://127.0.0.1:8123'" in source


def test_historical_error_displays_api_detail_without_raw_json():
    source = (ROOT / "frontend/src/hilegaHistoricalReplay.tsx").read_text(encoding="utf-8")
    assert "const payload=await r.json()" in source
    assert "if(typeof payload.detail==='string')message=payload.detail" in source
