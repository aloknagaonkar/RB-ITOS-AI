from pathlib import Path

def test_inventory_no_auto_scan():
    text=Path("frontend/src/historicalReplayInventory.tsx").read_text()
    assert "useEffect(()=>{void refresh()},[])" not in text
    assert "useEffect(() => { void refresh() }, [])" not in text

def test_readiness_no_auto_check():
    text=Path("frontend/src/historicalReplayOperations.tsx").read_text()
    assert "useEffect(()=>{ if(sessionDate) void refreshReadiness()" not in text

def test_request_has_timeout_or_existing_bounded_fetch():
    text=Path("frontend/src/historicalReplayOperations.tsx").read_text()
    assert ("timeoutMs=20000" in text) or ("AbortController" in text)
