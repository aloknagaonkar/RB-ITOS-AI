"""Upstox GET-only last-ten-session ATM +/-5 price research. No execution imports.

Historical Greeks and bid/ask are NOT reconstructed. The proposed top-five
selection rulebook remains unvalidated without recorded entry-time snapshots.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import os
import time
from collections import defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import quote
from dotenv import dotenv_values
from market_lab.domain import IST
from market_lab.gateways import UpstoxGateway, GatewayError, normalize_upstox_historical_candles
from market_lab.hilega_v2_alignment_replay_v1 import RULES, replay
from scripts.research_hilega_atm5_coverage import atm_for, build_index, check_trade, summarize as summarize_coverage
from scripts.research_hilega_strike_ranking import compare_trade, incomplete_trade, summarize as summarize_prices

UNDERLYING='NSE_INDEX|Nifty 50'
EXPECTED='five-minute-setup-1.2.0-pending-switch'


def write(path,value):
    path.parent.mkdir(parents=True,exist_ok=True)
    temp=path.with_name(path.name+'.tmp')
    with temp.open('w') as f:json.dump(value,f,indent=2);f.flush();os.fsync(f.fileno())
    os.replace(temp,path)


class ResearchGateway(UpstoxGateway):
    def __init__(self,token,root):
        super().__init__(token);self.root=root;self.last_request=0;self.sources={}
    def _get(self,path,params):
        allowed=('/v3/historical-candle/','/v2/option/contract','/v2/expired-instruments/expiries',
                 '/v2/expired-instruments/option/contract','/v2/expired-instruments/historical-candle/')
        if not any(path.startswith(prefix) for prefix in allowed):raise ValueError('RESEARCH_GET_ROUTE_NOT_ALLOWED')
        identity=json.dumps(dict(path=path,params=params),sort_keys=True)
        filename=hashlib.sha256(identity.encode()).hexdigest()+'.json';dest=self.root/filename
        if dest.exists():
            record=json.loads(dest.read_text())
            if record['request']!=json.loads(identity):raise ValueError('RESEARCH_CACHE_IDENTITY_MISMATCH')
            if hashlib.sha256(json.dumps(record['body'],sort_keys=True).encode()).hexdigest()!=record['body_sha256']:
                raise ValueError('RESEARCH_CACHE_HASH_MISMATCH')
        else:
            for attempt in range(3):
                time.sleep(max(0,.35-(time.monotonic()-self.last_request)))
                self.last_request=time.monotonic()
                try:body=super()._get(path,params);break
                except GatewayError as exc:
                    if attempt==2 or not any(term in str(exc).lower() for term in ('rate limit','network error')):raise
                    time.sleep(2**attempt)
            record=dict(request=json.loads(identity),received_at=datetime.now(IST).isoformat(),body=body,
                        body_sha256=hashlib.sha256(json.dumps(body,sort_keys=True).encode()).hexdigest())
            write(dest,record)
        self.sources[str(dest)]=record['body_sha256']
        return record['body']


def group_underlying(body):
    grouped=defaultdict(list)
    if not isinstance(body.get('data',{}).get('candles'),list):raise ValueError('UNDERLYING_CANDLE_SCHEMA_INVALID')
    for row in body['data']['candles']:
        stamp=datetime.fromisoformat(row[0].replace('Z','+00:00'))
        if stamp.tzinfo is None:raise ValueError('UNDERLYING_TIMEZONE_REQUIRED')
        grouped[stamp.astimezone(IST).date().isoformat()].append(row)
    result={}
    for day,values in grouped.items():
        candles=normalize_upstox_historical_candles(UNDERLYING,date.fromisoformat(day),dict(data=dict(candles=values)))
        result[day]=[dict(timestamp=c.timestamp.astimezone(IST).isoformat(),open=c.open,high=c.high,low=c.low,close=c.close,
                          volume=c.volume,open_interest=c.open_interest) for c in candles]
    return result


def choose_days(grouped,through,count=10):
    days=sorted(day for day,rows in grouped.items() if rows and day<=through)
    if len(days)<count+2:raise ValueError('NOT_ENOUGH_PROVIDER_SESSIONS_FOR_TEN_DAYS_AND_WARMUP')
    return days[-count:]


def nearest_expiry(day,expired_dates,active_contracts):
    expiries={date.fromisoformat(d).isoformat() for d in expired_dates}
    expiries.update(str(r['expiry']) for r in active_contracts if r.get('underlying_key')==UNDERLYING)
    eligible=sorted(e for e in expiries if e>=day)
    if not eligible:raise ValueError('PROVIDER_EXPIRY_SCHEDULE_MISSING')
    return eligible[0]


def freeze_contracts(trade,catalog,expiry):
    side='CE' if trade['direction']=='BULLISH' else 'PE'
    if trade['direction'] not in {'BULLISH','BEARISH'}:raise ValueError('UNKNOWN_DIRECTION')
    atm=atm_for(trade['entry_price']);out=[]
    for role in range(-5,6):
        matches=[c for c in catalog if c.side==side and c.strike==atm+role*50 and c.expiry.isoformat()==expiry]
        if len(matches)!=1:raise ValueError('EXACT_CONTRACT_MISSING_OR_AMBIGUOUS')
        c=matches[0]
        if type(c.lot_size) is not int or c.lot_size<=0:raise ValueError('PROVIDER_LOT_SIZE_MISSING')
        out.append(dict(role=role,option_type=side,strike=c.strike,expiry=expiry,instrument_key=c.instrument_key,lot_size=c.lot_size))
    return dict(strategy_entry_time=trade['entry_time'],nearest_expiry_verified=True,
                expiry=expiry,atm=atm,strike_interval=50,contracts=out,
                expiry_verification_basis='UPSTOX_EXPIRY_SCHEDULE_AND_EXACT_CONTRACT_CATALOG')


def run(args,gateway,output):
    begin=args.through_date-timedelta(days=28);through=args.through_date.isoformat()
    body=gateway._get(f'/v3/historical-candle/{quote(UNDERLYING,safe="")}/minutes/1/{through}/{begin.isoformat()}',{})
    grouped=group_underlying(body);days=choose_days(grouped,through)
    print('Selected provider sessions:',', '.join(days),flush=True)
    expired=gateway._get('/v2/expired-instruments/expiries',{'instrument_key':UNDERLYING})['data']
    active=gateway._get('/v2/option/contract',{'instrument_key':UNDERLYING})['data']
    if not isinstance(expired,list) or not isinstance(active,list):raise ValueError('PROVIDER_EXPIRY_SCHEMA_INVALID')
    manifests={};all_coverage=[];all_prices=[];day_report=[];issues=[]
    provider_today=datetime.now(IST).date()
    for day in days:
        warm=[(d,grouped[d]) for d in sorted(grouped) if d<day]
        result=replay(day,grouped[day],warm,dict(source='LAST10_UPSTOX_READ_ONLY',chart_parity_verified=False))
        if result['strategy_version']!=EXPECTED:raise ValueError('REPLAY_VERSION_CHANGED')
        write(output/'replays'/(day+'.json'),result)
        trades=result.get('trades') or [];expiry=nearest_expiry(day,expired,active)
        is_active=date.fromisoformat(expiry)>=provider_today
        catalog=gateway.active_option_contracts(UNDERLYING,date.fromisoformat(expiry)) if is_active else gateway.historical_option_contracts(UNDERLYING,date.fromisoformat(expiry))
        write(output/'contracts'/(day+'.json'),dict(session_date=day,expiry=expiry,
              nearest_expiry_basis='UPSTOX_EXPIRY_SCHEDULE',contracts=[c.model_dump(mode='json') for c in catalog]))
        frozen={};needed={}
        for n,trade in enumerate(trades,1):
            side='CE' if trade['direction']=='BULLISH' else 'PE'
            atm=atm_for(trade['entry_price'])
            for c in catalog:
                if c.side==side and c.strike in {atm+r*50 for r in range(-5,6)}:
                    needed[c.instrument_key]=dict(instrument_key=c.instrument_key,strike=c.strike,option_type=c.side,expiry=expiry,lot_size=c.lot_size)
            try:
                frozen[str(n)]=freeze_contracts(trade,catalog,expiry)
                for c in frozen[str(n)]['contracts']:needed[c['instrument_key']]=c
            except ValueError as exc:issues.append(dict(session_date=day,trade_index=n,issue=str(exc)))
        rows=[]
        for key,c in sorted(needed.items()):
            candles=gateway.active_option_historical_candles(key,date.fromisoformat(day)) if is_active else gateway.historical_option_candles(key,date.fromisoformat(day))
            for candle in candles:
                rows.append(SimpleNamespace(session_date=day,expiry=expiry,underlying=UNDERLYING,
                    instrument_key=key,strike=c['strike'],side=c['option_type'],timestamp=candle.timestamp.astimezone(IST),
                    open=candle.open,high=candle.high,low=candle.low,close=candle.close,
                    volume=candle.volume,open_interest=candle.open_interest))
        serialized=[{**vars(r),'timestamp':r.timestamp.isoformat()} for r in rows]
        cache_path=output/'data/historical-option-ohlc-cache-last10'/(f'NSE_INDEX_Nifty_50__{day}__{expiry}__w5.json')
        write(cache_path,dict(schema_version=1,status='AVAILABLE' if rows else 'UNAVAILABLE',session_date=day,expiry=expiry,
              underlying=UNDERLYING,wings=5,strike_interval=50,rows=serialized,row_count=len(rows),issues=[],provenance='UPSTOX_HISTORICAL_CANDLE_RECONSTRUCTION'))
        session=SimpleNamespace(session_date=day,expiry=expiry,strike_interval=50,rows=rows,source_path=str(cache_path))
        index=build_index([session],day)
        # Contract existence is catalog evidence, even when its candle path is empty.
        for c in needed.values():index['identities'][(c['option_type'],c['strike'])].add(c['instrument_key'])
        for n,trade in enumerate(trades,1):
            coverage=check_trade(trade,day,n,index,lag_minutes=args.lag_minutes)
            for row in coverage:
                row['nearest_expiry_verified']=True
                row['lot_size_verified']=str(n) in frozen
                row['expiry_verification_basis']='UPSTOX_EXPIRY_SCHEDULE_AND_EXACT_CONTRACT_CATALOG'
            all_coverage.extend(coverage)
            if str(n) not in frozen:
                prices=incomplete_trade(day,trade,n,'EXACT_ELEVEN_CONTRACT_METADATA_UNAVAILABLE',wings=5)
            else:
                prices=compare_trade(trade,session,lag_minutes=args.lag_minutes,trade_index=n,frozen=frozen[str(n)],
                    round_trip_cost_rupees=args.round_trip_cost_rupees,slippage_points_per_side=args.slippage_points_per_side,wings=5)
            all_prices.extend(prices)
        manifests[day]=frozen
        day_report.append(dict(session_date=day,expiry=expiry,accepted_trades=len(trades),frozen_trade_manifests=len(frozen),
                               fetched_contracts=len(needed),option_rows=len(rows)))
        print(day_report[-1],flush=True)
    write(output/'contract-manifest.json',manifests)
    coverage_summary=summarize_coverage(all_coverage,train_through=args.train_through)
    for summary in coverage_summary:
        summary['nearest_expiry_verified']=True
        summary['expiry_verification_basis']='UPSTOX_EXPIRY_SCHEDULE_AND_EXACT_CONTRACT_CATALOG'
    report=dict(model='HILEGA_LAST10_ATM5_PRICE_RESEARCH_V1',strategy_version=EXPECTED,session_dates=days,
        sessions=len(days),candidate_count=11,selection_approved=False,order_enabled=False,
        lag_minutes=args.lag_minutes,round_trip_cost_rupees=args.round_trip_cost_rupees,
        slippage_points_per_side=args.slippage_points_per_side,
        rulebook_status='NOT_VALIDATED_HISTORICAL_GREEKS_AND_BID_ASK_UNAVAILABLE',
        unvalidated_filters=['ENTRY_DELTA_BAND','TOP5_DELTA_RANKING','QUOTE_AGE','BID_ASK_SPREAD','DEPTH','THETA','GAMMA','IV'],
        coverage_summary=coverage_summary,
        price_summary=summarize_prices(all_prices,train_through=args.train_through,wings=5),
        days=day_report,issues=issues,coverage_legs=all_coverage,price_legs=all_prices,
        source_sha256=gateway.sources,
        warning='Price outcome comparison, not validation of executable Top5 choices. All eleven candidates are compared, not selected with hindsight. Minute opens are proxies, not fills. Ten days are exploratory and not enough to establish an optimal policy. No expiry/DTE Greek model or historical quote data is invented.')
    write(output/'report.json',report)
    print(json.dumps({k:v for k,v in report.items() if k not in {'coverage_legs','price_legs','source_sha256'}},indent=2),flush=True)
    return report


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--through-date',type=date.fromisoformat,required=True)
    p.add_argument('--output-root',type=Path,required=True)
    p.add_argument('--env-file',type=Path,default=Path('.env'))
    p.add_argument('--lag-minutes',type=int,choices=(0,1),default=1)
    p.add_argument('--round-trip-cost-rupees',type=float,required=True)
    p.add_argument('--slippage-points-per-side',type=float,required=True)
    p.add_argument('--train-through',default='2026-07-13')
    a=p.parse_args()
    import math
    if a.through_date>=datetime.now(IST).date():p.error('Use a completed prior session date; today is excluded')
    if any(not math.isfinite(v) or v<0 for v in (a.round_trip_cost_rupees,a.slippage_points_per_side)):p.error('Nonnegative finite costs required')
    if RULES['version']!=EXPECTED:p.error('Start research with HILEGA_PENDING_OPPOSITE_SWITCH_ENABLED=1 in the process environment')
    values=dotenv_values(a.env_file);token=os.getenv('UPSTOX_ACCESS_TOKEN') or values.get('UPSTOX_ACCESS_TOKEN')
    if not token:p.error('UPSTOX_ACCESS_TOKEN missing in VM environment/.env; do not share credentials')
    output=a.output_root.resolve()
    config=dict(through_date=a.through_date.isoformat(),lag_minutes=a.lag_minutes,strategy_version=EXPECTED,
                round_trip_cost_rupees=a.round_trip_cost_rupees,slippage_points_per_side=a.slippage_points_per_side,
                train_through=a.train_through,provider_as_of=datetime.now(IST).date().isoformat(),source_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest())
    if (output/'run-config.json').exists() and json.loads((output/'run-config.json').read_text())!=config:
        p.error('Use a new output directory for changed research configuration')
    write(output/'run-config.json',config)
    gateway=ResearchGateway(token,output/'raw-upstox-get-responses')
    try:
        report=run(a,gateway,output)
        if not report['issues'] and all(r['all_roles_coverage_pct']==100 for r in report['coverage_summary']):
            print('PRICE_DATA_COMPLETE; TOP5_RULEBOOK_NOT_VALIDATED')
        else:print('PRICE_DATA_INCOMPLETE; TOP5_RULEBOOK_NOT_VALIDATED')
    except Exception as exc:
        # Never print arbitrary HTTP request details, headers, credentials or responses.
        safe={'INCOMPLETE_STRATEGY_MINUTES','EXACT_1455_OPEN_REQUIRED','INDICATOR_WARMUP_NOT_READY',
              'NOT_ENOUGH_PROVIDER_SESSIONS_FOR_TEN_DAYS_AND_WARMUP','PROVIDER_EXPIRY_SCHEDULE_MISSING',
              'REPLAY_VERSION_CHANGED','RESEARCH_CACHE_HASH_MISMATCH','RESEARCH_CACHE_IDENTITY_MISMATCH'}
        issue=str(exc) if isinstance(exc,GatewayError) or str(exc) in safe else type(exc).__name__
        write(output/'failure.json',dict(status='INCOMPLETE',error=issue,order_enabled=False))
        raise SystemExit('Research incomplete: '+issue+'; inspect failure.json and share only sanitized output') from None
    finally:gateway.close()

if __name__=='__main__':main()
