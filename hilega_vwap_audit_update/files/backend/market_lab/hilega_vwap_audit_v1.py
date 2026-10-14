"""Read-only VWAP enrichment; immutable strategy audit and execution untouched."""
import json
import math
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
LIVE = ROOT/'data/live-observation/hilega-vwap-signal-v1/signal-vwap-observations.jsonl'
REPORT = ROOT/'data/research/hilega-vwap-oct13-14/report.json'


def instant(value):
    at=datetime.fromisoformat(str(value).replace('Z','+00:00'))
    if at.tzinfo is None:
        raise ValueError('TIMEZONE_REQUIRED')
    return at


def finite(value):
    return isinstance(value,(int,float)) and not isinstance(value,bool) and math.isfinite(value)


def inspect(at, live=LIVE, report=REPORT):
    target=instant(at)
    result=dict(status='NOT_RECORDED',observation_only=True,entry_filter_enabled=False,
                decision_timestamp=target.isoformat(),rows=[],issues=[])
    candidates=[]
    try:
        if live.exists():
            with live.open('rb') as f:
                f.seek(0,2);size=f.tell();offset=max(0,size-4*1024*1024);f.seek(offset)
                if offset:f.readline()
                for line in f.read().splitlines(keepends=True):
                    if not line.endswith(b'\n'):continue
                    try:candidates.append((json.loads(line),'OBSERVATION_JOURNAL'))
                    except (ValueError,UnicodeError):result['issues'].append('INVALID_JOURNAL_RECORD')
        if report.exists():
            if report.stat().st_size>16*1024*1024:
                result['issues'].append('RESEARCH_REPORT_SIZE_LIMIT')
            else:
                candidates.extend((r,'RECONSTRUCTED_RESEARCH_REPORT') for r in json.loads(report.read_text()).get('rows',[]))
    except (OSError,ValueError,TypeError,AttributeError):
        result['issues'].append('VWAP_SOURCE_READ_ERROR')
    seen=set()
    for source,origin in candidates:
        try:
            if instant(source.get('signal_time'))!=target:continue
            identity=(source['kind'],source['direction'],source['source'])
            if identity in seen:continue
            if source.get('status')!='AVAILABLE':
                result['issues'].append(source.get('reason','VWAP_UNAVAILABLE'));continue
            if source.get('basis')!='NIFTY_FUTURES_SESSION_5M_TYPICAL_PRICE_PROXY':
                raise ValueError('UNSUPPORTED_VWAP_BASIS')
            if source['kind'] not in ('SETUP','CONFIRMED_ENTRY') or source['direction'] not in ('BULLISH','BEARISH'):
                raise ValueError('INVALID_OBSERVATION_IDENTITY')
            if not all(finite(source.get(k)) for k in ('vwap','futures_close','distance_points')) or min(source['vwap'],source['futures_close'])<=0:
                raise ValueError('INVALID_VWAP_NUMBERS')
            available=instant(source['candle_available_at'])
            if available>target or available.date()!=target.date():
                raise ValueError('NONCAUSAL_VWAP_CANDLE')
            distance=source['futures_close']-source['vwap']
            if abs(distance-source['distance_points'])>1e-6:
                raise ValueError('VWAP_DISTANCE_MISMATCH')
            position='ABOVE' if distance>0 else 'BELOW' if distance<0 else 'AT'
            row=dict(source,origin=origin,price_position=position,
                     direction_agrees_with_vwap=position==('ABOVE' if source['direction']=='BULLISH' else 'BELOW'),
                     age_at_signal_seconds=(target-available).total_seconds())
            result['rows'].append(row);seen.add(identity)
        except (ValueError,TypeError,KeyError,AttributeError):
            result['issues'].append('INVALID_OR_NONCAUSAL_VWAP_RECORD')
    if result['rows']:result['status']='AVAILABLE'
    result['issues']=list(dict.fromkeys(result['issues']))
    return result
