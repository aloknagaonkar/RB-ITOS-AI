"""Pinned-account Upstox contract/quote GET-only preview. Never places orders."""
import argparse,json,os
from datetime import datetime,timezone
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request,build_opener,HTTPRedirectHandler
from urllib.error import HTTPError,URLError
from dotenv import dotenv_values
from rules import *
from market_lab.hilega_production_account_adapter_v1 import read_pin,matches,AdapterBlocked
from market_lab.hilega_production_broker_observation_v1 import Client,sanitize

class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self,*a,**k):return None
class MarketClient:
    def __init__(self,token):self.token=token;self.opener=build_opener(NoRedirect())
    def get(self,name,keys=None):
        if name=='contracts':path='/v2/option/contract';params={'instrument_key':UNDERLYING}
        elif name=='quotes':
            if not keys or len(keys)>11 or any(not isinstance(k,str) or not (k==UNDERLYING or k.startswith('NSE_FO|')) for k in keys):raise Blocked('QUOTE_KEYS_INVALID')
            path='/v2/market-quote/quotes';params={'instrument_key':','.join(keys)}
        elif name=='market':path='/v2/market/status/NSE';params={}
        else:raise Blocked('GET_ENDPOINT_NOT_ALLOWED')
        url='https://api.upstox.com'+path+('?' + urlencode(params) if params else '')
        req=Request(url,headers={'Authorization':'Bearer '+self.token,'Accept':'application/json',
            'User-Agent':'RB-ITOS-AI/1.0 (read-only contract readiness validation)'},method='GET')
        try:
            with self.opener.open(req,timeout=8) as r:raw=r.read(8_000_001)
            if len(raw)>8_000_000:raise Blocked('RESPONSE_TOO_LARGE')
            value=json.loads(raw)
        except HTTPError as exc:raise Blocked('MARKET_API_HTTP_'+str(exc.code)) from None
        except (URLError,TimeoutError):raise Blocked('MARKET_API_NETWORK_OR_TIMEOUT') from None
        if not isinstance(value,dict) or value.get('status')!='success':raise Blocked('MARKET_API_RESPONSE_FAILED')
        return value.get('data')

def capture(a):
    config=dotenv_values(a.env_file)
    def setting(name):
        f=config.get(name);e=os.environ.get(name)
        if f and e and f!=e:raise Blocked('ENV_FILE_SHELL_CONFLICT_'+name)
        return e or f
    token=setting('HILEGA_PRODUCTION_BROKER_READ_TOKEN') or setting('UPSTOX_ACCESS_TOKEN')
    if not token:raise Blocked('READ_TOKEN_MISSING')
    pin=read_pin(a.pin_file);account=Client(token);market=MarketClient(token)
    start=datetime.now(timezone.utc);matches(account.get('profile'),pin)
    opening=market.get('market')
    if not isinstance(opening,dict) or opening.get('exchange')!='NSE':raise Blocked('MARKET_STATUS_SCHEMA_INVALID')
    underlying=quote_map(market.get('quotes',[UNDERLYING]),[UNDERLYING])[UNDERLYING]
    contracts=market.get('contracts');offsets=[int(x) for x in a.offsets.split(',')]
    mapping=select(contracts,underlying.get('last_price'),offsets,a.lots,start.astimezone(IST).date(),a.expiry)
    keys=[UNDERLYING]+[x['instrument_key'] for x in mapping['contracts']]
    quotes=quote_map(market.get('quotes',keys),keys)
    funds=sanitize(account.get('funds'),'funds')
    if funds.get('status')!='PASS':raise Blocked('FUNDS_UNAVAILABLE_OR_INVALID')
    closing=market.get('market');matches(account.get('profile'),pin);end=datetime.now(timezone.utc)
    if not isinstance(closing,dict) or closing.get('exchange')!='NSE':raise Blocked('MARKET_STATUS_SCHEMA_INVALID')
    if (end-start).total_seconds()>30 or start.astimezone(IST).date()!=end.astimezone(IST).date():raise Blocked('CAPTURE_WINDOW_EXCEEDED')
    refreshed=select(contracts,quotes[UNDERLYING].get('last_price'),offsets,a.lots,end.astimezone(IST).date(),a.expiry)
    if refreshed['atm']!=mapping['atm']:raise Blocked('ATM_CHANGED_DURING_CAPTURE_RERUN')
    spotage=(end-timestamp(quotes[UNDERLYING].get('timestamp'))).total_seconds()
    status=closing.get('status') if opening.get('status')==closing.get('status') else 'CHANGED_DURING_CAPTURE'
    report=assess(mapping,quotes,funds['cash_available_to_trade'],status,end,number(a.buffer),max_age=10,max_spread=number(a.max_spread,True))
    if not 0<=spotage<=10:
        for basket in report['baskets']:
            basket['preview_checks_passed']=False;basket['reasons'].append('UNDERLYING_QUOTE_STALE_OR_FUTURE')
    passed=all(x['preview_checks_passed'] for x in report['baskets'])
    report.update(model='HILEGA_READONLY_CONTRACT_PREVIEW_V1',status='READ_ONLY_CHECKS_PASS' if passed else 'NOT_CLEARED',
        generated_at=end.isoformat(),capture_started_at=start.isoformat(),market_status=status,account_identity_verified=True,
        spot=str(number(quotes[UNDERLYING]['last_price'],True)),spot_quote_age_seconds=round(spotage,3),
        expiry=mapping['expiry'],atm=mapping['atm'],inferred_strike_step=mapping['inferred_strike_step'],
        atm_tie_rule=mapping['atm_tie_rule'],quote_api='V2_FULL_MARKET_QUOTES',max_quote_age_seconds=10,
        max_last_trade_age_seconds=60,max_spread_pct=a.max_spread,thresholds_approved_for_production=False,
        funds_field='data.available_to_trade.cash_available_to_trade.total',pledge_included=False,
        allocation_reserved=False,charges_are_estimated_buffer_only=True,orders_sent=False,
        plus_stream_entitlement='NOT_VALIDATED',production_readiness='NOT_CLEARED_FOR_PRODUCTION')
    return report

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--env-file',type=Path,default=Path('.env'))
    p.add_argument('--pin-file',type=Path,default=Path.home()/'hilega-private/upstox-account-pin.json')
    p.add_argument('--offsets',default='0');p.add_argument('--lots',type=int,default=1)
    p.add_argument('--expiry',help='Optional exact YYYY-MM-DD; default nearest nonexpired returned expiry')
    p.add_argument('--buffer',default='100',help='Provisional INR per-leg cost buffer; not verified charges')
    p.add_argument('--max-spread',default='2',help='Provisional percent limit, not a strategy rule')
    p.add_argument('--output',required=True,type=Path);a=p.parse_args()
    if a.output.exists():raise Blocked('OUTPUT_EXISTS_USE_FRESH_DIRECTORY')
    a.output.mkdir(parents=True,mode=0o700)
    try:report=capture(a)
    except (Blocked,AdapterBlocked) as exc:report=dict(status='BLOCKED',reason=str(exc),entry_permission=False,production_execution_enabled=False,orders_sent=False)
    except Exception as exc:report=dict(status='BLOCKED',reason='UNEXPECTED_SCHEMA_OR_TRANSPORT_ERROR',error_type=type(exc).__name__,entry_permission=False,production_execution_enabled=False,orders_sent=False)
    path=a.output/'report.json';path.write_text(json.dumps(report,indent=2));path.chmod(0o600)
    lines=['# Read-only contract and quote preview','',
        'No orders. Draft quality thresholds and cost buffer; no allocation reservation or production permission.','',
        '| Side | Offset | Strike | Expiry | Lot / quantity | Bid | Ask | Quote age s | Cost incl. buffer | Reasons |',
        '|---|---:|---:|---|---|---:|---:|---:|---:|---|']
    for x in report.get('legs',[]):
        vals=[x['side'],x['offset'],x['strike'],x['expiry'],str(x['lot_size'])+' / '+str(x['quantity']),x.get('bid'),x.get('ask'),x.get('quote_age_seconds'),x.get('estimated_cost'),', '.join(x['reasons']) or 'Preview checks passed']
        lines.append('| '+' | '.join(str(v).replace('|','/') for v in vals)+' |')
    lines+=['','Status: '+report['status']]
    if report.get('reason'):lines+=['Reason: '+report['reason']]
    for x in report.get('baskets',[]):lines+=[x['side']+' basket: cost '+str(x['estimated_cost'])+'; half-cash cap '+x['half_cash_cap']+'; '+(', '.join(x['reasons']) or 'Preview checks passed')]
    lines+=['','Production execution enabled: false. Orders sent: false.']
    text='\n'.join(lines)+'\n';(a.output/'summary.md').write_text(text);(a.output/'summary.md').chmod(0o600);print(text)
    return 0 if report['status']=='READ_ONLY_CHECKS_PASS' else 2
if __name__=='__main__':
    try:raise SystemExit(main())
    except Blocked as exc:print(json.dumps(dict(status='BLOCKED',reason=str(exc),orders_sent=False)));raise SystemExit(2)
