import json
from datetime import date
from pathlib import Path
from types import SimpleNamespace
import pytest
from market_lab import recovered_replay_ui_v1 as registry
from market_lab.hilega_expiry_rollover_v1 import resolve_expiry

def test_expired_env_is_ignored_in_auto(monkeypatch):
    monkeypatch.delenv('HILEGA_OPTION_EXPIRY_MODE', raising=False)
    calls = []
    def resolve(key, today):
        calls.append((key, today)); return date(2026, 10, 13)
    expiry, source = resolve_expiry(SimpleNamespace(resolve_option_expiry=resolve), session_date=date(2026, 10, 8), configured_raw='2026-10-06')
    assert expiry == date(2026, 10, 13)
    assert source == 'AUTO_UPSTOX_INSTRUMENT_SEARCH'
    assert calls == [('NSE_INDEX|Nifty 50', date(2026, 10, 8))]

def test_manual_expired_fails(monkeypatch):
    monkeypatch.setenv('HILEGA_OPTION_EXPIRY_MODE', 'MANUAL')
    with pytest.raises(ValueError, match='expired'):
        resolve_expiry(None, session_date=date(2026, 10, 8), configured_raw='2026-10-06')

def test_auto_invalid_provider_fails(monkeypatch):
    monkeypatch.setenv('HILEGA_OPTION_EXPIRY_MODE', 'AUTO')
    with pytest.raises(ValueError, match='unexpired'):
        resolve_expiry(SimpleNamespace(resolve_option_expiry=lambda *a, **k: date(2026, 10, 6)), session_date=date(2026, 10, 8))

def test_expiry_rolls_on_next_date(monkeypatch):
    monkeypatch.setenv('HILEGA_OPTION_EXPIRY_MODE', 'AUTO')
    sources = SimpleNamespace(resolve_option_expiry=lambda key, today: date(2026, 10, 6) if today <= date(2026, 10, 6) else date(2026, 10, 13))
    assert resolve_expiry(sources, session_date=date(2026, 10, 6))[0] == date(2026, 10, 6)
    assert resolve_expiry(sources, session_date=date(2026, 10, 7))[0] == date(2026, 10, 13)

def test_recovery_registry_does_not_replace_live_source(tmp_path, monkeypatch):
    monkeypatch.setattr(registry, 'ROOT', tmp_path)
    day = '2026-10-06'; path = tmp_path / 'hilega' / day; path.mkdir(parents=True)
    payload = {'session_date': day, 'evidence_cohort': registry.LABEL, 'execution_enabled': False}
    (path / 'v2.json').write_text(json.dumps(payload))
    original = [{'session_date': day, 'source': 'DIRECTIONAL_LIVE_SHADOW', 'available_sources': ['DIRECTIONAL_LIVE_SHADOW']}]
    rows = registry.hilega_sessions(original)
    assert rows[0]['source'] == 'DIRECTIONAL_LIVE_SHADOW'
    assert registry.LABEL in rows[0]['available_sources']
    assert original[0]['available_sources'] == ['DIRECTIONAL_LIVE_SHADOW']
    assert registry.load_hilega(day, 'V2') == payload
    assert registry.load_hilega(day, 'V1') is None

def test_api_routes_recovery_before_frozen(tmp_path, monkeypatch):
    from market_lab import hilega_historical_ui_api_v1 as api
    monkeypatch.setattr(registry, 'ROOT', tmp_path)
    day = '2026-10-07'; path = tmp_path / 'hilega' / day; path.mkdir(parents=True)
    payload = {'session_date': day, 'evidence_cohort': registry.LABEL, 'reports': [], 'execution_enabled': False}
    (path / 'v1.json').write_text(json.dumps(payload))
    assert api.strategy_test(day, 'V1') == payload

def test_midpoint_registry_preserves_frozen(tmp_path, monkeypatch):
    monkeypatch.setattr(registry, 'ROOT', tmp_path)
    path = tmp_path / 'midpoint'; path.mkdir()
    (path / 'manifest.json').write_text(json.dumps({'sessions': [{'session_date': '2026-10-06', 'block': registry.LABEL}]}))
    original = {'sessions': [{'session_date': '2026-09-30'}]}
    assert len(registry.midpoint_manifest(original)['sessions']) == 2
    assert len(original['sessions']) == 1

def test_worker_daily_guard_present():
    root = Path(__file__).parents[1]
    source = (root / 'backend/market_lab/live_shadow_worker_v1.py').read_text()
    assert source.count('# AUTO_EXPIRY_DAILY_GUARD') == 2

def test_midpoint_route_uses_recovered_dir(tmp_path, monkeypatch):
    from market_lab.midpoint_strategy import live_shadow_ui as api
    monkeypatch.setattr(registry, 'ROOT', tmp_path)
    path = tmp_path / 'midpoint' / '2026-10-06'; path.mkdir(parents=True)
    (path / 'audit.jsonl').touch()
    assert api._historical_session_dir('2026-10-06') == path

@pytest.mark.parametrize('direction,side', [('BULLISH', 'CE'), ('BEARISH', 'PE')])
def test_sandbox_contract_selection_rolls_automatically(direction, side):
    import httpx
    from market_lab.hilega_upstox_sandbox_execution_v1 import UpstoxTransport
    transport = UpstoxTransport.__new__(UpstoxTransport)
    contracts = [{'expiry': expiry, 'instrument_type': kind, 'strike_price': 22550,
        'instrument_key': expiry + kind, 'lot_size': 65}
        for expiry in ['2026-10-06', '2026-10-13', '2026-10-20'] for kind in ['CE', 'PE']]
    def request(req):
        return httpx.Response(200, json={'status': 'success', 'data':
            {'nifty': {'last_price': 22555}} if 'ltp' in req.url.path else contracts})
    with httpx.Client(base_url='https://mock.invalid', transport=httpx.MockTransport(request)) as client:
        transport.analytics = client
        selected = transport.resolve_atm(direction, date(2026, 10, 7))
    assert selected['expiry'] == '2026-10-13'
    assert selected['option_type'] == side
    assert selected['lot_size'] == 65
