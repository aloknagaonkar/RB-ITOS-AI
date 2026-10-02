from datetime import date
from pathlib import Path
from market_lab.historical_oi_build_job_v1 import build_command, build_paths, validate_request

def test_validate_request():
    sd,ex=validate_request("2026-09-09","2026-09-15")
    assert sd==date(2026,9,9) and ex==date(2026,9,15)

def test_reject_expiry_before_session():
    try: validate_request("2026-09-09","2026-09-08")
    except ValueError: return
    raise AssertionError("Expected ValueError")

def test_command_uses_existing_positioning_sidecar():
    cmd=build_command("2026-09-09","2026-09-15")
    assert "market_lab.historical_positioning_sidecar" in cmd
    assert str(build_paths("2026-09-09")["positioning_csv"]) in cmd

def test_ui_and_routes_are_wired():
    api=Path("backend/market_lab/historical_replay_operations_api_v1.py").read_text()
    assert '@router.post("/historical-oi/build")' in api
    ui=Path("frontend/src/historicalOiResearch.tsx").read_text()
    assert "HistoricalOiBuildPanel" in ui
