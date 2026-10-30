import json
from datetime import datetime
import pytest
from market_lab import hilega_vwap_audit_v1 as m
from hilega_vwap_signal_review.collect import signals, vwap_at, dt

AT='2026-10-15T09:26:00+05:30'


def row(**kwargs):
    value=dict(signal_time=AT,kind='CONFIRMED_ENTRY',direction='BULLISH',source='ENTRY',
               status='AVAILABLE',basis='NIFTY_FUTURES_SESSION_5M_TYPICAL_PRICE_PROXY',
               vwap=100.,futures_close=101.,distance_points=1.,
               candle_available_at='2026-10-15T09:25:00+05:30')
    value.update(kwargs);return value


def setup(tmp_path, rows=()):
    live=tmp_path/'live'/'signal-vwap-observations.jsonl'
    live.parent.mkdir();live.write_text(''.join(json.dumps(r)+'\n' for r in rows))
    report=tmp_path/'research'/'report.json';report.parent.mkdir()
    return live,report


def save_candles(folder, *, missing=False, future=True):
    (folder/'2026-10-15-futures-contract.json').write_text(json.dumps(dict(
        instrument_key='NSE_FO|FUT',underlying_key='NSE_INDEX|Nifty 50',expiry='2026-10-27')))
    candles=[['2026-10-15T09:15:00+05:30',100,102,98,100,10],
             ['2026-10-15T09:20:00+05:30',100,104,100,103,20]]
    if missing:candles=candles[1:]
    if future:candles.append(['2026-10-15T09:25:00+05:30',100,1000,100,999,10000])
    (folder/'2026-10-15-futures-ohlcv.json').write_text(json.dumps(dict(data=dict(candles=candles))))


def test_waiting_checkpoint_is_collected_and_partial_audit_line_is_ignored(tmp_path):
    audit=tmp_path/'audit.jsonl'
    record=dict(stage='DIRECTIONAL_DECISION',status='PROCESSED',sequence=1,payload=dict(
        decision_timestamp=AT,strategy_id='HILEGA_V2_ALIGNMENT_DUAL_EXIT',
        trade_owner_after='NONE',trade_owner_before='NONE',setup_attempts=[],event_details=[]))
    audit.write_text(json.dumps(record)+'\n'+json.dumps(record))
    result=signals(audit,'2026-10-15')
    assert len(result)==1 and result[0]['kind']=='DECISION_CHECKPOINT'
    assert result[0]['direction']=='NONE'


def test_exit_checkpoint_retains_owner_context_without_becoming_an_entry(tmp_path):
    audit=tmp_path/'audit'
    audit.write_text(json.dumps(dict(stage='DIRECTIONAL_SESSION_CUTOFF',status='PROCESSED',payload=dict(
        decision_timestamp=AT,strategy_id='HILEGA_V2_ALIGNMENT_DUAL_EXIT',
        trade_owner_before='BEARISH',trade_owner_after='NONE',event_details=[])))+'\n')
    assert signals(audit,'2026-10-15')[0]['direction']=='BEARISH'


def test_setup_and_entry_identities_are_preserved(tmp_path):
    audit=tmp_path/'audit'
    audit.write_text(json.dumps(dict(stage='DIRECTIONAL_DECISION',status='PROCESSED',payload=dict(
        decision_timestamp=AT,strategy_id='HILEGA_V2_ALIGNMENT_DUAL_EXIT',
        setup_attempts=[dict(direction='BULLISH',source='V1_CANONICAL')],
        event_details=[dict(event_type='ENTRY_PATH1',entry_time=AT,entry_price=22500)])))+'\n')
    assert {r['kind'] for r in signals(audit,'2026-10-15')}=={'SETUP','CONFIRMED_ENTRY'}


def test_valid_journal_remains_preferred(tmp_path):
    live,report=setup(tmp_path,[row()])
    report.write_text(json.dumps(dict(rows=[row(vwap=99.,distance_points=2.)])))
    save_candles(live.parent)
    result=m.inspect(AT,live,report)
    assert len(result['rows'])==1 and result['rows'][0]['vwap']==100.
    assert result['rows'][0]['origin']=='OBSERVATION_JOURNAL'


def test_checkpoint_reconstruction_is_causal_and_explicit(tmp_path):
    live,report=setup(tmp_path);save_candles(live.parent)
    result=m.inspect(AT,live,report)
    value=result['rows'][0]
    assert value['origin']=='RECONSTRUCTED_FROM_SAVED_FUTURES'
    assert value['kind']=='DECISION_CHECKPOINT' and value['direction_agrees_with_vwap'] is None
    assert value['candle_count']==2 and value['futures_close']==103
    assert value['age_at_signal_seconds']==60 and value['vwap']<104


def test_incomplete_session_cannot_produce_reconstructed_vwap(tmp_path):
    live,report=setup(tmp_path);save_candles(live.parent,missing=True)
    result=m.inspect(AT,live,report)
    assert not result['rows'] and 'INCOMPLETE_FUTURES_SESSION_PATH' in result['issues']


def test_equivalent_timezone_uses_indian_session_date(tmp_path):
    live,report=setup(tmp_path);save_candles(live.parent)
    result=m.inspect('2026-10-15T03:56:00Z',live,report)
    assert result['rows'][0]['futures_close']==103


def test_collector_unavailable_reason_is_visible(tmp_path):
    live,report=setup(tmp_path)
    (live.parent/'report.json').write_text(json.dumps(dict(rows=[row(status='UNAVAILABLE',reason='ZERO_CUMULATIVE_VOLUME')])))
    result=m.inspect(AT,live,report)
    assert not result['rows'] and 'ZERO_CUMULATIVE_VOLUME' in result['issues']


def test_old_neighbour_checkpoint_is_never_relabelled(tmp_path):
    live,report=setup(tmp_path,[row(signal_time='2026-10-15T09:25:00+05:30')])
    assert not m.inspect(AT,live,report)['rows']


@pytest.mark.parametrize('available',['2026-10-15T09:30:00+05:30','2026-10-15T09:20:00+05:30'])
def test_future_or_stale_evidence_is_rejected(tmp_path,available):
    live,report=setup(tmp_path,[row(candle_available_at=available)])
    assert not m.inspect(AT,live,report)['rows']


def test_report_is_read_even_when_journal_read_fails(tmp_path):
    live,report=setup(tmp_path)
    live.unlink();live.mkdir()
    report.write_text(json.dumps(dict(rows=[row()])))
    result=m.inspect(AT,live,report)
    assert result['rows'] and 'VWAP_JOURNAL_READ_ERROR' in result['issues']


def test_first_bar_is_unavailable_until_completed(tmp_path):
    live,report=setup(tmp_path);save_candles(live.parent)
    assert not m.inspect('2026-10-15T09:19:00+05:30',live,report)['rows']


def test_wrong_underlying_cannot_be_used_as_nifty_vwap(tmp_path):
    live,report=setup(tmp_path);save_candles(live.parent)
    path=live.parent/'2026-10-15-futures-contract.json'
    payload=json.loads(path.read_text());payload['underlying_key']='NSE_INDEX|BANKNIFTY'
    path.write_text(json.dumps(payload))
    assert not m.inspect(AT,live,report)['rows']


def test_today_collection_uses_intraday_and_records_checkpoint(tmp_path,monkeypatch):
    from datetime import date
    from types import SimpleNamespace
    from hilega_vwap_signal_review import collect as collector
    from market_lab import upstox_live_futures_v1 as gateway_module
    paths=[]
    class Clock(datetime):
        @classmethod
        def now(cls,tz=None):return datetime.fromisoformat('2026-10-15T10:00:00+05:30')
    class Gateway:
        def __init__(self,token):assert token=='test-token'
        def resolve_nifty_front_future(self,**kwargs):
            return gateway_module.FuturesInstrument('NSE_FO|FUT','NIFTY',date(2026,10,27),65,'NSE_INDEX|Nifty 50','NIFTY')
        def _get(self,path):
            paths.append(path)
            return dict(data=dict(candles=[
                ['2026-10-15T09:15:00+05:30',100,102,98,100,10],
                ['2026-10-15T09:20:00+05:30',100,104,100,103,20]]))
        def close(self):pass
    monkeypatch.setattr(collector,'datetime',Clock)
    monkeypatch.setattr(gateway_module,'UpstoxLiveFuturesGatewayV1',Gateway)
    monkeypatch.setenv('UPSTOX_ACCESS_TOKEN','test-token')
    audit=tmp_path/'audit.jsonl'
    audit.write_text(json.dumps(dict(stage='DIRECTIONAL_DECISION',status='PROCESSED',payload=dict(
        decision_timestamp=AT,strategy_id='HILEGA_V2_ALIGNMENT_DUAL_EXIT',
        trade_owner_after='NONE',event_details=[])))+'\n')
    output=tmp_path/'out'
    collector.collect(SimpleNamespace(dates=['2026-10-15'],audit=audit,output=output))
    assert len(paths)==1 and '/intraday/' in paths[0]
    result=m.inspect(AT,output/'signal-vwap-observations.jsonl',tmp_path/'missing-report')
    assert result['rows'][0]['kind']=='DECISION_CHECKPOINT'
    assert result['rows'][0]['reconstructed'] is True
