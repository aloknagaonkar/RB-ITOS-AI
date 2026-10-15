"""Read-only ATM +/-5 coverage at accepted HILEGA replay entry and exit times.

No fetching, orders, execution changes or policy approval. An expiry inferred
from the caches is only the nearest CACHED expiry, not verified nearest expiry.
Historical reconstruction keys are evidence identities, not live order tokens.
"""
from __future__ import annotations
import argparse
import json
import math
import re
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from market_lab.historical_option_ohlc_adapter_v1 import load_option_ohlc_file
from scripts.research_hilega_strike_ranking import REPLAY_MODEL, STRATEGY, minute, roles_for


def atm_for(spot, step=50):
    spot=float(spot)
    if not math.isfinite(spot) or spot<=0 or step!=50:
        raise ValueError('INVALID_UNDERLYING_ENTRY_PRICE_OR_STEP')
    lower=math.floor(spot/step)*step
    return min((lower,lower+step),key=lambda x:(abs(x-spot),x))


def build_index(sessions, day):
    valid=[s for s in sessions if s.session_date==day and s.expiry>=day and s.strike_interval==50]
    expiry=min((s.expiry for s in valid),default=None)
    identities=defaultdict(set); series=defaultdict(dict); conflicts=set(); sources=[]
    for s in valid:
        if s.expiry!=expiry:continue
        sources.append(s.source_path)
        for c in s.rows:
            if c.session_date!=day or c.expiry!=expiry or c.underlying!='NSE_INDEX|Nifty 50':continue
            if c.side not in {'CE','PE'}:continue
            identities[(c.side,c.strike)].add(c.instrument_key)
            key=(c.side,c.strike,c.instrument_key)
            values=(c.open,c.high,c.low,c.close,c.volume,c.open_interest)
            if c.timestamp in series[key] and series[key][c.timestamp]!=values:
                conflicts.add((key,c.timestamp))
            series[key][c.timestamp]=values
    return dict(expiry=expiry,identities=identities,series=series,conflicts=conflicts,sources=sources)


def check_trade(trade, day, trade_index, index, *, lag_minutes=1, wings=5):
    if trade['direction'] not in {'BULLISH','BEARISH'}:raise ValueError('UNKNOWN_DIRECTION')
    side='CE' if trade['direction']=='BULLISH' else 'PE'
    atm=atm_for(trade['entry_price'])
    start=minute(trade['entry_time'],lag_minutes);end=minute(trade['exit_time'],lag_minutes)
    if start.date().isoformat()!=day or end.date().isoformat()!=day:
        raise ValueError('TRADE_SESSION_MISMATCH')
    from datetime import timedelta
    expected=[start+timedelta(minutes=n) for n in range(int((end-start).total_seconds()//60)+1)]
    out=[]
    for role in roles_for(wings):
        strike=atm+role*50;keys=index['identities'].get((side,strike),set())
        base=dict(session_date=day,trade_index=trade_index,trade_id=trade.get('trade_id'),
                  direction=trade['direction'],option_type=side,atm=atm,role=role,strike=strike,
                  cached_expiry=index['expiry'],nearest_expiry_verified=False,lot_size_verified=False,
                  strategy_entry_time=trade['entry_time'],strategy_exit_time=trade['exit_time'],
                  research_entry_time=start.isoformat(),research_exit_time=end.isoformat(),
                  expected_minutes=len(expected),instrument_key=next(iter(keys)) if len(keys)==1 else None)
        issue=None;missing=[]
        if end<=start:issue='NONPOSITIVE_HOLDING_PERIOD'
        elif index['expiry'] is None:issue='OPTION_CACHE_UNAVAILABLE'
        elif not keys:issue='EXACT_STRIKE_CONTRACT_MISSING'
        elif len(keys)!=1:issue='AMBIGUOUS_CONTRACT_IDENTITY'
        else:
            key=(side,strike,next(iter(keys)));series=index['series'][key]
            missing=[ts for ts in expected if ts not in series]
            if missing:issue='MISSING_EXACT_OPTION_MINUTES'
            elif any((key,ts) in index['conflicts'] for ts in expected):issue='CONFLICTING_OPTION_MINUTES'
            elif any(not all(math.isfinite(float(v)) for v in series[ts][:4])
                     or not 0<series[ts][2]<=min(series[ts][0],series[ts][3])
                     or max(series[ts][0],series[ts][3])>series[ts][1] for ts in expected):
                issue='INVALID_OPTION_PRICE'
        out.append(dict(base,path_status='INCOMPLETE' if issue else 'EXACT_CACHE_PATH_AVAILABLE',
                        issue=issue,missing_minute_count=len(missing),
                        first_missing_minute=missing[0].isoformat() if missing else None))
    return out


def summarize(rows, *, train_through='2026-07-13', wings=5):
    grouped=defaultdict(list);trade_roles=defaultdict(set)
    for r in rows:
        split='TRAIN' if r['session_date']<=train_through else 'VALIDATION'
        grouped[(split,r['direction'])].append(r)
        if r['path_status']=='EXACT_CACHE_PATH_AVAILABLE':
            trade_roles[(r['session_date'],r['trade_index'])].add(r['role'])
    complete={k for k,roles in trade_roles.items() if roles==set(roles_for(wings))}
    out=[]
    for (split,direction),group in sorted(grouped.items()):
        trades={(r['session_date'],r['trade_index']) for r in group}
        available=[r for r in group if r['path_status']=='EXACT_CACHE_PATH_AVAILABLE']
        common=len(trades & complete)
        out.append(dict(split=split,direction=direction,expected_trades=len(trades),
                        expected_contract_paths=len(group),exact_cached_paths=len(available),
                        path_coverage_pct=100*len(available)/len(group),
                        all_roles_complete_trades=common,all_roles_coverage_pct=100*common/len(trades),
                        candidate_count=len(roles_for(wings)),nearest_expiry_verified=False,
                        incomplete_reasons=dict(Counter(r['issue'] for r in group if r['issue'])),
                        per_role=[dict(role=role,expected_trades=len(trades),
                                       complete_paths=sum(r['role']==role for r in available)) for role in roles_for(wings)]))
    return out


def cache_paths_by_day(root):
    by_day=defaultdict(list);issues=[]
    for path in sorted(root.glob('historical-option-ohlc-cache*/*.json')):
        match=re.search(r'__(\d{4}-\d{2}-\d{2})__',path.name)
        if match:
            by_day[match.group(1)].append(path)
        else:
            try:by_day[str(json.loads(path.read_text())['session_date'])].append(path)
            except Exception as exc:issues.append(dict(path=str(path),issue=type(exc).__name__))
    return by_day,issues


def load_sessions(paths,day):
    sessions=[];issues=[]
    for path in paths:
        try:
            # Reject naive source timestamps before the adapter normalizes to IST.
            raw=json.loads(path.read_text())
            if raw.get('session_date')!=day:raise ValueError('CACHE_FILENAME_DATE_MISMATCH')
            for row in raw.get('rows',[]):
                stamp=datetime.fromisoformat(row['timestamp'].replace('Z','+00:00'))
                if stamp.tzinfo is None:raise ValueError('OPTION_TIMESTAMP_TIMEZONE_REQUIRED')
            sessions.append(load_option_ohlc_file(path))
        except Exception as exc:issues.append(dict(path=str(path),issue=str(exc) if isinstance(exc,ValueError) else type(exc).__name__))
    return sessions,issues


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--replay-root',type=Path,default=Path('data/historical-evidence/hilega-v2-alignment-dual-exit-v1'))
    p.add_argument('--data-root',type=Path,default=Path('data'))
    p.add_argument('--from-date',default='2026-04-15');p.add_argument('--through-date',default='2026-10-13')
    p.add_argument('--train-through',default='2026-07-13')
    p.add_argument('--expected-version',default='five-minute-setup-1.2.0-pending-switch')
    p.add_argument('--lag-minutes',type=int,choices=(0,1),default=1)
    p.add_argument('--output',type=Path)
    args=p.parse_args()
    paths=[path for path in sorted(args.replay_root.glob('????-??-??.json')) if args.from_date<=path.stem<=args.through_date]
    if not paths:p.error('No replay files; refusing empty success')
    caches,issues=cache_paths_by_day(args.data_root);rows=[];days=[]
    for path in paths:
        day=path.stem;replay=json.loads(path.read_text())
        if replay.get('model')!=REPLAY_MODEL or replay.get('strategy_id')!=REPLAY_MODEL or replay.get('session_date')!=day:
            raise ValueError('REPLAY_IDENTITY_MISMATCH:'+str(path))
        if replay.get('strategy_version')!=args.expected_version:
            raise ValueError('REPLAY_VERSION_MISMATCH:'+str(path)+':'+str(replay.get('strategy_version')))
        sessions,errors=load_sessions(caches.get(day,[]),day);issues.extend(errors)
        index=build_index(sessions,day);trades=replay.get('trades') or []
        days.append(dict(session_date=day,accepted_trades=len(trades),cached_expiry=index['expiry'],source_paths=index['sources']))
        for n,trade in enumerate(trades,1):
            rows.extend(check_trade(trade,day,n,index,lag_minutes=args.lag_minutes))
    report=dict(model='HILEGA_ATM5_CACHE_COVERAGE_V1',strategy_id=STRATEGY,
                expected_strategy_version=args.expected_version,wings=5,candidate_count=11,
                lag_minutes=args.lag_minutes,train_through=args.train_through,
                selection_approved=False,order_enabled=False,
                expected_trade_count=sum(d['accepted_trades'] for d in days),replay_days=len(days),
                replay_dates_without_usable_cache=[d['session_date'] for d in days if d['cached_expiry'] is None],
                summary=summarize(rows,train_through=args.train_through),days=days,cache_issues=issues,legs=rows,
                warning='Exact cache paths only. Nearest cached expiry is not verified nearest eligible expiry. Historical lot sizes, bid/ask, Greeks and actual fills are not established. Reconstruction instrument keys must not be used for live orders. No strike ranking or exchange-calendar completeness is claimed.')
    encoded=json.dumps(report,indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True,exist_ok=True);args.output.write_text(encoded+'\n')
        print(json.dumps({k:v for k,v in report.items() if k not in {'legs','days','cache_issues'}},indent=2))
        print('Full report:',args.output)
    else:print(encoded)

if __name__=='__main__':main()
