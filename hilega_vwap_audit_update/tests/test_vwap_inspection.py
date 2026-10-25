import importlib.util
import json
from pathlib import Path

spec=importlib.util.spec_from_file_location('vwap_view',Path(__file__).resolve().parents[1]/'files/backend/market_lab/hilega_vwap_audit_v1.py')
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
AT='2026-10-14T13:48:00+05:30'


def row(**kwargs):
    r=dict(signal_time=AT,kind='CONFIRMED_ENTRY',direction='BULLISH',source='ENTRY',
           status='AVAILABLE',basis='NIFTY_FUTURES_SESSION_5M_TYPICAL_PRICE_PROXY',
           vwap=22711.0,futures_close=22643.0,distance_points=-68.0,
           candle_available_at='2026-10-14T13:45:00+05:30')
    r.update(kwargs);return r


def test_missing(tmp_path):
    assert m.inspect(AT,tmp_path/'missing',tmp_path/'other')['status']=='NOT_RECORDED'


def test_exact_and_equivalent_timezone(tmp_path):
    p=tmp_path/'report';p.write_text(json.dumps({'rows':[row()]}))
    x=m.inspect('2026-10-14T08:18:00+00:00',tmp_path/'missing',p)
    assert x['rows'][0]['direction_agrees_with_vwap'] is False
    assert x['rows'][0]['age_at_signal_seconds']==180


def test_later_candle_rejected(tmp_path):
    p=tmp_path/'r';p.write_text(json.dumps({'rows':[row(candle_available_at='2026-10-14T13:50:00+05:30')]}))
    assert not m.inspect(AT,tmp_path/'m',p)['rows']


def test_other_checkpoint_not_substituted(tmp_path):
    p=tmp_path/'r';p.write_text(json.dumps({'rows':[row(signal_time='2026-10-14T13:47:00+05:30')]}))
    assert m.inspect(AT,tmp_path/'m',p)['status']=='NOT_RECORDED'


def test_journal_preferred_and_partial_ignored(tmp_path):
    p=tmp_path/'r';p.write_text(json.dumps({'rows':[row()]}))
    j=tmp_path/'j';j.write_text(json.dumps(row(vwap=22600.,distance_points=43.))+'\n'+json.dumps(row()))
    x=m.inspect(AT,j,p)
    assert len(x['rows'])==1 and x['rows'][0]['origin']=='OBSERVATION_JOURNAL'
    assert x['rows'][0]['direction_agrees_with_vwap'] is True


def test_invalid_distance(tmp_path):
    p=tmp_path/'r';p.write_text(json.dumps({'rows':[row(distance_points=0.)]}))
    assert not m.inspect(AT,tmp_path/'m',p)['rows']
