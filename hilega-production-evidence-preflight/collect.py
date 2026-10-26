"""Reuse fixed GET-only collectors; collect fresh evidence without order transport."""
import uuid
from datetime import datetime,timezone
from evidence import ROOT,MODEL,MODE,FLAGS,Blocked,need,dependencies,load,fresh_window
from market_lab.hilega_production_account_adapter_v1 import matches,sign,day
from market_lab.hilega_production_broker_observation_v1 import Client


def collectors():
    rules,_=dependencies()
    market=load(ROOT/'hilega-production-contract-preview/run.py','preflight_market_collector',{'rules':rules})
    analysis=load(ROOT/'hilega-production-cash-observation/analysis.py','preflight_cash_analysis')
    cash=load(ROOT/'hilega-production-cash-observation/run.py','preflight_cash_collector',{'analysis':analysis})
    return rules,market,cash,analysis


def capture(token,pin):
    rules,market_module,cash_module,analysis=collectors()
    account=Client(token);market=market_module.MarketClient(token)
    start=datetime.now(timezone.utc)
    matches(account.get('profile'),pin)
    before=analysis.funds(account.get('funds'))
    opening=market.get('market')
    initial=rules.quote_map(market.get('quotes',[rules.UNDERLYING]),[rules.UNDERLYING])[rules.UNDERLYING]
    contracts=market.get('contracts')
    mapping=rules.select(contracts,initial['last_price'],[0],1,start.astimezone(rules.IST).date())
    keys=[rules.UNDERLYING]+[r['instrument_key'] for r in mapping['contracts']]
    quotes=rules.quote_map(market.get('quotes',keys),keys)
    cash=cash_module.capture(account,pin)
    need(cash.get('status')=='READ_ONLY_CAPTURED','CASH_CAPTURE_UNAVAILABLE')
    closing=market.get('market')
    after=analysis.funds(account.get('funds'))
    matches(account.get('profile'),pin)
    end=datetime.now(timezone.utc)
    fresh_window(start.isoformat(),end.isoformat(),end.isoformat())
    fields=('instrument_key','underlying_key','instrument_type','segment','exchange','expiry',
            'strike_price','lot_size','minimum_lot','freeze_quantity','tick_size')
    # Retain the nearest expiry strike grid needed to independently reselect ATM.
    selected=[{k:r[k] for k in fields} for r in contracts if isinstance(r,dict) and
              r.get('underlying_key')==rules.UNDERLYING and r.get('segment')=='NSE_FO' and
              r.get('exchange')=='NSE' and r.get('expiry')==mapping['expiry'] and
              r.get('instrument_type') in {'CE','PE'}]
    safe_quotes={}
    for key,q in quotes.items():
        row={k:q[k] for k in ('instrument_token','last_price','timestamp')}
        if key!=rules.UNDERLYING:
            row.update(last_trade_time=q['last_trade_time'],volume=q['volume'],depth={
                side:[{k:d[k] for k in ('price','quantity')} for d in q['depth'][side]]
                for side in ('buy','sell')})
        safe_quotes[key]=row
    value=dict(model=MODEL,evidence_mode=MODE,snapshot_id=uuid.uuid4().hex,
        account_scope=pin['scope'],started_at=start.isoformat(),completed_at=end.isoformat(),
        session_date=day(end),profile_verified_before_and_after=True,
        market_before={k:opening[k] for k in ('exchange','status')},
        market_after={k:closing[k] for k in ('exchange','status')},
        cash_before_market=before,cash_after_market=after,cash_capture=cash,
        spot_initial=initial['last_price'],contracts=selected,quotes=safe_quotes,**FLAGS)
    value['signature']=sign(value,pin)
    return value
