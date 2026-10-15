"""GET-only VWAP comparison of saved, version-verified strategy replays.

Separate from recorded-live audit and all running collectors/workers.
"""
import argparse
import csv
import json
import os
from dataclasses import asdict
from datetime import date,datetime
from pathlib import Path
from urllib.parse import quote
from zoneinfo import ZoneInfo

from hilega_vwap_signal_review.collect import dt,vwap_at

IST=ZoneInfo('Asia/Kolkata')


def replay_entries(payload,day,expected):
    if payload.get('strategy_version')!=expected:
        raise ValueError('REPLAY_VERSION_MISMATCH')
    if payload.get('session_date')!=day:
        raise ValueError('REPLAY_SESSION_MISMATCH')
    trades=payload.get('trades')
    if not isinstance(trades,list):raise ValueError('REPLAY_TRADES_MISSING')
    keys=set();entries=[]
    for trade in trades:
        at=dt(trade['entry_time'])
        if at.date().isoformat()!=day or trade['direction'] not in ('BULLISH','BEARISH'):
            raise ValueError('INVALID_REPLAY_ENTRY')
        key=(trade['direction'],at.isoformat())
        if key in keys:raise ValueError('DUPLICATE_REPLAY_ENTRY')
        keys.add(key)
        entries.append(dict(kind='CONFIRMED_ENTRY',direction=trade['direction'],
            source=trade.get('setup_source','REPLAY_ACCEPTED_ENTRY'),
            signal_time=at.isoformat(),setup_time=trade.get('signal_time'),
            entry_price=trade['entry_price'],exit_time=trade.get('exit_time'),exit_price=trade.get('exit_price'),
            trade_points=trade.get('points'),exit_reason=trade.get('exit_reason'),
            strategy_version=expected,session_date=day,evidence_source='VERSION_VERIFIED_RESEARCH_REPLAY'))
    return entries


def main():
    from dotenv import load_dotenv
    from market_lab.upstox_live_futures_v1 import UpstoxLiveFuturesGatewayV1
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--replay-root',type=Path,required=True)
    p.add_argument('--expected-version',required=True)
    p.add_argument('--dates',nargs='+',default=['2026-10-06','2026-10-07','2026-10-08','2026-10-09','2026-10-12'])
    p.add_argument('--output',type=Path,default=Path('data/research/hilega-vwap-previous5-replay'))
    a=p.parse_args();a.output.mkdir(parents=True,exist_ok=True)
    load_dotenv();token=os.environ.get('UPSTOX_ACCESS_TOKEN')
    if not token:raise SystemExit('UPSTOX_ACCESS_TOKEN_MISSING')
    gateway=UpstoxLiveFuturesGatewayV1(token);rows=[];coverage=[]
    try:
        for day in a.dates:
            record=dict(session_date=day,status='UNAVAILABLE',entries=0,available=0)
            try:
                session=date.fromisoformat(day)
                saved=a.replay_root/(day+'.json')
                if not saved.is_file():raise ValueError('REPLAY_FILE_MISSING')
                entries=replay_entries(json.loads(saved.read_text()),day,a.expected_version)
                record['entries']=len(entries)
                if not entries:
                    record['status']='NO_ACCEPTED_ENTRIES';coverage.append(record);continue
                current=datetime.now(IST).date()
                if (session.year,session.month)!=(current.year,current.month):raise ValueError('HISTORICAL_FUTURES_MANIFEST_REQUIRED')
                instrument=gateway.resolve_nifty_front_future(today=session)
                (a.output/(day+'-contract.json')).write_text(json.dumps(asdict(instrument),default=str,indent=2))
                key=quote(instrument.instrument_key,safe='')
                body=gateway._get(f'/v3/historical-candle/{key}/minutes/5/{day}/{day}')
                candles=body.get('data',{}).get('candles',[])
                if not any(str(r[0])[:10]==day for r in candles) and session==current:
                    body=gateway._get(f'/v3/historical-candle/intraday/{key}/minutes/5')
                    candles=body.get('data',{}).get('candles',[])
                (a.output/(day+'-futures.json')).write_text(json.dumps(body,indent=2))
                for item in entries:
                    row=dict(item,instrument_key=instrument.instrument_key)
                    try:
                        row.update(vwap_at(candles,dt(item['signal_time'])),status='AVAILABLE')
                        row['direction_agrees_with_vwap']=row['price_position']==('ABOVE' if row['direction']=='BULLISH' else 'BELOW')
                        record['available']+=1
                    except (ValueError,TypeError,KeyError,IndexError) as exc:
                        row.update(status='UNAVAILABLE',reason=str(exc) if isinstance(exc,ValueError) else 'INVALID_FUTURES_DATA')
                    rows.append(row)
                record['status']='AVAILABLE' if record['available']==record['entries'] else 'INCOMPLETE_VWAP'
            except Exception as exc:
                record['reason']=str(exc) if isinstance(exc,ValueError) and str(exc).replace('_','').isupper() else type(exc).__name__
            coverage.append(record)
    finally:gateway.close()
    complete=all(c['status'] in ('AVAILABLE','NO_ACCEPTED_ENTRIES') for c in coverage)
    report=dict(status='COMPLETE' if complete else 'INCOMPLETE',expected_version=a.expected_version,
                observation_only=True,entry_filter_enabled=False,coverage=coverage,rows=rows,
                warning='Reconstructed research entries, not original live decisions. Futures typical-price VWAP proxy, not index VWAP. Classification only, not a replay with a VWAP gate enabled.')
    (a.output/'report.json').write_text(json.dumps(report,indent=2)+'\n')
    columns=['session_date','direction','setup_time','signal_time','entry_price','exit_time','exit_price','trade_points','futures_close','vwap','price_position','distance_points','direction_agrees_with_vwap','strategy_version','status','reason']
    with (a.output/'entries.csv').open('w',newline='') as f:
        w=csv.DictWriter(f,fieldnames=columns,extrasaction='ignore');w.writeheader();w.writerows(rows)
    print(json.dumps(dict(status=report['status'],coverage=coverage,report=str(a.output/'report.json')),indent=2))


if __name__=='__main__':main()
