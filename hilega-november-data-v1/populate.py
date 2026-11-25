#!/usr/bin/env python3
"""Audit/recover November candles and populate current-policy research replay."""
import argparse
import csv
from datetime import date,datetime,time,timedelta
import hashlib
import json
import os
from pathlib import Path
import sys
from time import monotonic,sleep
from urllib.request import urlopen
from zoneinfo import ZoneInfo

IST=ZoneInfo('Asia/Kolkata')
VERSION='bullish-gap2-full-wma2-3.0.2-3m-bounded-warmup'


def days_between(start,end,calendar):
    result=[];cursor=start
    while cursor<=end:
        if calendar(cursor):result.append(cursor)
        cursor+=timedelta(days=1)
    return result


def assess(index,day,warmup):
    key=day.isoformat();path=index.get(key)
    if path is None:return dict(status='MISSING',path=None,minutes=0)
    try:
        rows=warmup.read_session(path,day)
        return dict(status='VALID',path=str(path),minutes=len(rows),sha256=hashlib.sha256(Path(path).read_bytes()).hexdigest())
    except (ValueError,KeyError,TypeError,OSError) as exc:
        return dict(status='INVALID',path=str(path),minutes=None,error_type=type(exc).__name__)


def registry(base):
    try:
        with urlopen(base.rstrip('/')+'/api/live-shadow/hilega-historical/sessions',timeout=30) as response:body=json.load(response)
        return {r['session_date']:r for r in body.get('sessions',[])},None
    except Exception as exc:return {},type(exc).__name__


def saved_status(e,day):
    path=Path(e.OUTPUT_ROOT)/(day.isoformat()+'.json')
    if not path.is_file():return 'MISSING'
    try:
        x=json.loads(path.read_text())
        return 'SAVED_VERSION_MATCH_NOT_YET_REVALIDATED' if x.get('strategy_version')==VERSION else 'OLD_OR_OTHER_VERSION'
    except (ValueError,OSError):return 'INVALID'


def validate_result(result,day,version):
    if (result.get('session_date')!=day.isoformat() or result.get('strategy_version')!=version or
        result.get('execution_enabled') is not False or result.get('observation_only') is not True):
        raise ValueError('REPLAY_IDENTITY_OR_SCOPE_INVALID')
    for t in result.get('trades') or []:
        if not t.get('exit_time') or str(t['exit_time'])[:10]!=day.isoformat():
            raise ValueError('REPLAY_UNCLOSED_OR_WRONG_DATE_TRADE')
    return next(iter(result.get('performance_summary') or []),{})


def fetch_complete(source,day,warmup,now):
    try:return warmup.fetch_session(source,day)
    except Exception:
        # Brokers can expose today's completed session only via intraday until
        # the historical store updates. Validate every real minute identically.
        if day!=now.date():raise
        items=source.nifty_intraday_1m(now=now)
        rows=[dict(timestamp=x.timestamp.isoformat(),open=x.open,high=x.high,
                   low=x.low,close=x.close,volume=getattr(x,'volume',None)) for x in items]
        return warmup.validate_rows(rows,day)


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--repo',type=Path,default=Path.cwd())
    p.add_argument('--through',default='2026-11-23')
    p.add_argument('--populate',action='store_true',help='Recover invalid/missing data and generate replay results')
    p.add_argument('--api-url',default='http://127.0.0.1:8123')
    a=p.parse_args();repo=a.repo.resolve();os.chdir(repo);sys.path.insert(0,str(repo/'backend'))
    from market_lab.hilega_three_minute_v1 import warmup as w
    from market_lab.hilega_three_minute_v1 import hilega_combined_replay_v1 as e
    if e.VERSION!=VERSION:raise ValueError('DEPLOYED_REPLAY_VERSION_CHANGED')
    today=datetime.now(IST);end=date.fromisoformat(a.through);start=date(2026,11,1)
    if not start<=end<=date(2026,11,30) or end>today.date():raise ValueError('COMPLETED_NOVEMBER_RANGE_REQUIRED')
    if end==today.date() and today.time()<time(15,35):raise ValueError('TODAY_NOT_YET_COMPLETE_USE_PREVIOUS_SESSION')
    targets=days_between(start,end,w.session_day)
    required=sorted(set(targets).union(*(set(w.required_sessions(d)) for d in targets)))
    index=e.cache_index();visible,registry_error=registry(a.api_url)
    initial={d.isoformat():assess(index,d,w) for d in required}
    report=dict(model='HILEGA_NOVEMBER_DATA_POPULATION_V1',strategy_version=VERSION,
        started_at=today.isoformat(),through=end.isoformat(),populate_requested=a.populate,
        initial_registry_error=registry_error,required_candle_sessions=len(required),
        initial_missing_or_invalid=[dict(session_date=k,**v) for k,v in initial.items() if v['status']!='VALID'],
        sessions=[],recovery=[],services_restarted=False,application_source_modified=False,
        live_journals_modified=False,broker_orders_sent=False,scope='UNDERLYING_RESEARCH_ONLY')
    for day in targets:
        key=day.isoformat();needed=w.required_sessions(day)
        report['sessions'].append(dict(session_date=key,initial_candles=initial[key],
            initially_listed_in_ui=key in visible,initial_replay=saved_status(e,day),
            warmup_first=needed[0].isoformat(),warmup_last=needed[-1].isoformat(),
            missing_or_invalid_warmup=[d.isoformat() for d in needed if initial[d.isoformat()]['status']!='VALID']))
    print('NOVEMBER AUDIT — before recovery',flush=True)
    print('Date | Candles | Listed in UI | Saved replay | Missing/invalid warmup',flush=True)
    for row in report['sessions']:
        print(' | '.join([row['session_date'],row['initial_candles']['status'],str(row['initially_listed_in_ui']),
            row['initial_replay'],str(len(row['missing_or_invalid_warmup']))]),flush=True)
    output=repo/'data/recovery'/('hilega-november-validation-'+today.strftime('%Y%m%dT%H%M%S%f'))
    output.mkdir(parents=True,exist_ok=False)
    def checkpoint():
        (output/'report.json').write_text(json.dumps(report,indent=2,allow_nan=False)+'\n')
    checkpoint();source=None;recovery_failed=[]
    try:
        if a.populate:
            missing=[d for d in required if initial[d.isoformat()]['status']!='VALID']
            if missing:
                from dotenv import load_dotenv
                from market_lab.upstox_live_shadow_sources_v1 import UpstoxLiveShadowSourcesV1
                load_dotenv(repo/'.env');token=os.getenv('UPSTOX_ACCESS_TOKEN','')
                if not token:raise ValueError('UPSTOX_ACCESS_TOKEN_MISSING')
                source=UpstoxLiveShadowSourcesV1(token);del token
            for n,day in enumerate(missing,1):
                print(f'Recovering candle session {n}/{len(missing)}: {day}',flush=True)
                try:
                    rows=None
                    for attempt in range(3):
                        try:
                            rows=fetch_complete(source,day,w,datetime.now(IST));break
                        except Exception:
                            if attempt==2:raise
                            sleep(1+2*attempt)
                    path=w.save_session(w.FRESH_ROOT,day,rows)
                    report['recovery'].append(dict(session_date=day.isoformat(),status='RECOVERED_VALIDATED',
                        path=str(path),minutes=len(rows),sha256=hashlib.sha256(path.read_bytes()).hexdigest()))
                except Exception as exc:
                    recovery_failed.append(day.isoformat())
                    report['recovery'].append(dict(session_date=day.isoformat(),status='FETCH_OR_VALIDATION_FAILED',error_type=type(exc).__name__))
                checkpoint()
            index=e.cache_index()
            for n,row in enumerate(report['sessions'],1):
                day=date.fromisoformat(row['session_date']);needed=w.required_sessions(day)
                row['candles_after']=assess(index,day,w)
                problems=[d.isoformat() for d in [*needed,day] if assess(index,d,w)['status']!='VALID']
                if problems:
                    row.update(result='DATA_INCOMPLETE',unavailable_inputs=problems);checkpoint();continue
                # The deployed runner requires 375 target minutes; never pad the
                # shortened session or publish a fabricated full-day artifact.
                if day==w.SPECIAL:
                    row.update(result='SPECIAL_TARGET_REPLAY_UNSUPPORTED',
                        note='70 validated minutes available for warmup; deployed target runner requires 375. No synthetic candles or misleading COMPLETE artifact created.')
                    checkpoint();continue
                print(f'Replaying session {n}/{len(targets)}: {day} — current policy, 20 verified seed sessions',flush=True)
                began=monotonic()
                try:
                    result=e.load_session(day.isoformat())
                    summary=validate_result(result,day,VERSION)
                    row.update(result='REPLAY_VALIDATED',seconds=round(monotonic()-began,2),
                        artifact=str(Path(e.OUTPUT_ROOT)/(day.isoformat()+'.json')),performance=summary,
                        total_peak_positive_points=round(sum(t.get('mfe_points',0) for t in result.get('trades') or []),2),
                        total_giveback_points=round(sum(t.get('giveback_points',0) for t in result.get('trades') or []),2))
                    print(f"  PASS: entries={summary.get('entries')} net={summary.get('net_points')} peak={row['total_peak_positive_points']} giveback={row['total_giveback_points']}",flush=True)
                except Exception as exc:
                    row.update(result='REPLAY_FAILED',error_type=type(exc).__name__,
                        error=str(exc) if type(exc).__name__ in ('ValueError','FileNotFoundError','ReplayBusyError') else 'See deployed replay runner; no source changes performed')
                    print('  Replay not completed:',row['error_type'],flush=True)
                checkpoint()
        else:
            for row in report['sessions']:row['result']='AUDIT_ONLY'
        visible_after,error=registry(a.api_url)
        for row in report['sessions']:row['listed_in_ui_after']=row['session_date'] in visible_after if error is None else None
        report.update(registry_error_after=error,finished_at=datetime.now(IST).isoformat(),
            recovered_candle_sessions=sum(x['status']=='RECOVERED_VALIDATED' for x in report['recovery']),
            replay_validated_sessions=sum(x.get('result')=='REPLAY_VALIDATED' for x in report['sessions']),
            remaining=[dict(session_date=x['session_date'],result=x.get('result')) for x in report['sessions']
                       if x.get('result') not in ('REPLAY_VALIDATED','AUDIT_ONLY') or (a.populate and x.get('listed_in_ui_after') is not True)])
        report['status']='AUDIT_ONLY' if not a.populate else 'POPULATION_COMPLETE' if not report['remaining'] else 'POPULATION_WITH_REMAINING_ITEMS'
        checkpoint()
        with (output/'sessions.csv').open('w',newline='') as f:
            fields=['session_date','result','initially_listed_in_ui','listed_in_ui_after','artifact','total_peak_positive_points','total_giveback_points']
            writer=csv.DictWriter(f,fieldnames=fields,extrasaction='ignore');writer.writeheader();writer.writerows(report['sessions'])
        print(json.dumps({k:report[k] for k in ['status','strategy_version','required_candle_sessions','recovered_candle_sessions','replay_validated_sessions','remaining']},indent=2))
        print('REPORT:',output/'report.json',flush=True)
        print('Refresh historical replay after completed sessions are generated.',flush=True)
    finally:
        if source is not None:source.close()
        checkpoint()


if __name__=='__main__':main()
