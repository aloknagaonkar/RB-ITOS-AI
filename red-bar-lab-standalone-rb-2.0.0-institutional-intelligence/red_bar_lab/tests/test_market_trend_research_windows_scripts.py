from pathlib import Path

ROOT = Path(".")


def _text(name: str) -> str:
    return (ROOT / name).read_text(encoding="utf-8")


def test_start_script_uses_hidden_argument_list_and_environment_token_only():
    source = _text("start_market_trend_research_worker.ps1")
    assert "Start-Process" in source
    assert "-WindowStyle Hidden" in source
    assert "$arguments = @(\"-m\"" in source
    assert "UPSTOX_ACCESS_TOKEN_MISSING" in source
    assert "$escapedToken" not in source
    assert "-ArgumentList $arguments" in source
    assert "run_market_trend_research_supervisor" in source


def test_stop_script_uses_worker_owned_request_and_no_broad_kill():
    source = _text("stop_market_trend_research_worker.ps1")
    assert "stop.request" in source
    assert "Move-Item" in source
    assert "taskkill /IM" not in source
    assert "Stop-Process -Name" not in source
    assert "python.exe" not in source


def test_status_script_handles_unavailable_status():
    source = _text("status_market_trend_research_worker.ps1")
    assert "STATUS_UNAVAILABLE" in source
    assert "India Standard Time" in source
    assert "Heartbeat age" in source
    assert "Authority" in source


def test_platform_launcher_integrates_explicit_worker_controls():
    source = _text("start_red_bar_platform.ps1")
    assert "StartMarketTrendResearchWorker" in source
    assert "start_market_trend_research_worker.ps1" in source
    assert "stop_market_trend_research_worker.ps1" in source
    assert "status_market_trend_research_worker.ps1" in source


def test_streamlit_does_not_start_or_control_supervisor():
    source = Path("red_bar_lab/ui/market_trend_research_panel.py").read_text(
        encoding="utf-8"
    )
    assert "run_market_trend_research_supervisor" not in source
    assert "stop.request" not in source
    assert "Start-Process" not in source
    assert "subprocess" not in source
