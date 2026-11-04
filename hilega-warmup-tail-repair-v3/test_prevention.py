"""Run on the VM against its native aggregation and the exact proposed writer."""
import ast,json,sys
from pathlib import Path
import pytest
from test_repair import DAY,rows
sys.path.insert(0,str(Path.cwd()/'backend'))
from market_lab import hilega_milega_historical_replay_v1 as native
from market_lab.gateways import normalize_upstox_historical_candles
SOURCE=Path(__file__).with_name('writer-candidate.py.txt').read_text()
node=next(n for n in ast.parse(SOURCE).body if isinstance(n,ast.FunctionDef) and n.name=='_write_cache')
space=dict(native.__dict__)
exec(compile(ast.Module(body=[node],type_ignores=[]),'candidate-writer','exec'),space)
write=space['_write_cache']
def candles(values):
    body={'data':{'candles':[[r[k] for k in ('timestamp','open','high','low','close','volume','open_interest')] for r in values]}}
    return normalize_upstox_historical_candles(native.UNDERLYING,DAY,body)
def test_truncated_fetch_preserves_existing_operational_bytes(tmp_path):
    p=tmp_path/'hilega-milega-underlying-cache-v1'/f'{DAY}.json';p.parent.mkdir();p.write_bytes(b'previous-evidence')
    with pytest.raises(ValueError):write(p,native.UNDERLYING,DAY,candles(rows()[:360]))
    assert p.read_bytes()==b'previous-evidence'
def test_missing_final_minute_does_not_create_operational_cache(tmp_path):
    p=tmp_path/'hilega-milega-underlying-cache-v1'/f'{DAY}.json'
    with pytest.raises(ValueError):write(p,native.UNDERLYING,DAY,candles(rows()[:-1]))
    assert not p.exists()
def test_duplicate_is_rejected_before_persistence(tmp_path):
    values=candles(rows());values.append(values[-1]);p=tmp_path/'hilega-milega-underlying-cache-v1'/f'{DAY}.json'
    with pytest.raises(ValueError):write(p,native.UNDERLYING,DAY,values)
    assert not p.exists()
def test_complete_cache_round_trips_native_full_session(tmp_path):
    p=tmp_path/'hilega-milega-underlying-cache-v1'/f'{DAY}.json';write(p,native.UNDERLYING,DAY,candles(rows()))
    value=native._read_cache(p,native.UNDERLYING,DAY)
    assert len(value)==375 and len(native.aggregate_exact_5m(value,DAY,require_full_session=True))==75
    assert not list(p.parent.glob('*.complete-*'))
def test_research_partial_cache_contract_is_preserved(tmp_path):
    p=tmp_path/'research'/f'{DAY}.json';write(p,native.UNDERLYING,DAY,candles(rows()[:10]))
    assert len(json.loads(p.read_text())['candles'])==10
