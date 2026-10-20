"""Isolated one-lot LIMIT BUY/fill/SELL probe. Sandbox only; run on VM.
Use --check for read-only plan, --test for isolated checks, and
--confirm SANDBOX_ONLY_LIMIT_ROUND_TRIP for submission. Never delete state.
"""
import argparse
import json
import math
import os
import time
import unittest
import uuid
from datetime import datetime, timedelta
from decimal import Decimal, ROUND_CEILING, ROUND_FLOOR
from pathlib import Path
from zoneinfo import ZoneInfo

IST=ZoneInfo('Asia/Kolkata')
ROOT=Path('data/research/hilega-sandbox-limit-lifecycle-v1')
HOST='https://api-sandbox.upstox.com'
PID=Path('data/hilega-upstox-sandbox-worker.pid')


def now():return datetime.now(IST)


def atomic(path,value):
    tmp=path.with_suffix('.tmp')
    with tmp.open('w') as stream:
        json.dump(value,stream,indent=2);stream.flush();os.fsync(stream.fileno())
    os.replace(tmp,path)


def timestamp(value):
    if value is None or isinstance(value,bool):raise ValueError('QUOTE_TIMESTAMP_REQUIRED')
    try:
        number=float(value)
        return datetime.fromtimestamp(number/1000 if number>1e11 else number,IST)
    except (ValueError,TypeError,OverflowError,OSError):
        parsed=datetime.fromisoformat(str(value).replace('Z','+00:00'))
        if parsed.tzinfo is None:raise ValueError('QUOTE_TIMEZONE_REQUIRED')
        return parsed.astimezone(IST)


def quote_plan(q,side,quantity,tick,budget,cushion,at):
    bid=Decimal(str(q['bid_price']));ask=Decimal(str(q['ask_price']));step=Decimal(str(tick))
    if not all(v.is_finite() and v>0 for v in (bid,ask,step)) or bid>ask:raise ValueError('INVALID_BID_ASK')
    if not 0<=(at-timestamp(q.get('quote_time'))).total_seconds()<=10:raise ValueError('STALE_OR_FUTURE_QUOTE')
    if min(int(q['bid_quantity']),int(q['ask_quantity']))<quantity:raise ValueError('INSUFFICIENT_TOP_OF_BOOK_DEPTH')
    if (ask-bid)/((ask+bid)/2)>Decimal('.02'):raise ValueError('SPREAD_EXCEEDS_TWO_PERCENT')
    rounding=ROUND_CEILING if side=='BUY' else ROUND_FLOOR
    base=ask if side=='BUY' else bid
    limit=((base/step).to_integral_value(rounding=rounding)+(cushion if side=='BUY' else -cushion))*step
    if limit<=0:raise ValueError('NONPOSITIVE_LIMIT')
    if side=='BUY' and limit*quantity>Decimal(str(budget)):raise ValueError('ONE_LOT_PREMIUM_BUDGET_EXCEEDED')
    return dict(limit_price=float(limit),quote=q,tick_size_rupees=float(step),cushion_ticks=cushion,
                quote_source='UPSTOX_LIVE_ANALYTICS_NOT_PROOF_OF_SANDBOX_MATCHING_PRICE')


def worker_stopped_and_flat(worker):
    if PID.exists():
        try:
            pid=int(PID.read_text().strip())
            os.kill(pid,0)
        except ProcessLookupError:pass
        except PermissionError:raise ValueError('SANDBOX_WORKER_PID_NOT_ACCESSIBLE')
        else:raise ValueError('STOP_SANDBOX_WORKER_WHILE_FLAT_BEFORE_DEMO')
    status=worker.status()
    if any(status.get(k) for k in ('open_legs','pending_fill_orders','uncertain_requests')):
        raise ValueError('STRATEGY_SANDBOX_REQUIRES_RECONCILIATION_NO_DEMO_BUY')
    return status


def trace(tr,order,log):
    """Best-effort read-only history/trade evidence. Unsupported APIs are logged."""
    for endpoint in ('history','trades'):
        try:
            response=tr.sandbox.get('/v2/order/'+endpoint,params={'order_id':order['order_id']})
            payload=response.json()
            if not response.is_success or payload.get('status')!='success':
                log('PROVIDER_READ_UNAVAILABLE',endpoint=endpoint,http_status=response.status_code,
                    error_codes=[e.get('errorCode') or e.get('error_code') for e in payload.get('errors',[])])
                continue
            data=payload.get('data');rows=data if isinstance(data,list) else [data]
            fields=('order_id','status','status_message','status_message_raw','instrument_token','transaction_type',
                    'order_type','quantity','filled_quantity','pending_quantity','average_price','price',
                    'exchange_order_id','order_timestamp','exchange_timestamp','trade_id','trade_price','traded_quantity')
            log('PROVIDER_'+endpoint.upper(),rows=[{k:r[k] for k in fields if k in r} for r in rows if isinstance(r,dict)])
        except Exception as exc:log('PROVIDER_READ_UNAVAILABLE',endpoint=endpoint,error_type=type(exc).__name__)


def position_check(tr,instrument,log):
    try:
        response=tr.sandbox.get('/v2/portfolio/short-term-positions')
        payload=response.json()
        if not response.is_success or payload.get('status')!='success' or not isinstance(payload.get('data'),list):
            raise ValueError('SANDBOX_POSITION_ENDPOINT_UNAVAILABLE')
        matches=[r for r in payload['data'] if r.get('instrument_token')==instrument]
        quantities=[int(r['quantity']) for r in matches]
        evidence=dict(status='VERIFIED',instrument=instrument,matching_positions=len(matches),quantities=quantities,flat=all(q==0 for q in quantities))
    except Exception as exc:evidence=dict(status='UNAVAILABLE',error_type=type(exc).__name__,flat=None)
    log('PROVIDER_POSITION_CHECK',**evidence)
    return evidence


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--check',action='store_true');p.add_argument('--test',action='store_true')
    p.add_argument('--confirm',choices=['SANDBOX_ONLY_LIMIT_ROUND_TRIP']);p.add_argument('--resume',action='store_true')
    p.add_argument('--max-premium-rupees',type=float,default=15000)
    p.add_argument('--tick-size-rupees',type=float,default=.05)
    p.add_argument('--cushion-ticks',type=int,default=2)
    p.add_argument('--timeout-seconds',type=int,default=120)
    args=p.parse_args()
    if args.test:
        result=unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(Checks))
        raise SystemExit(0 if result.wasSuccessful() else 1)
    if not args.check and not args.confirm:p.error('--check or explicit Sandbox confirmation required')
    if not 15<=args.timeout_seconds<=300 or not 0<=args.cushion_ticks<=5:p.error('Timeout 15..300; cushion 0..5 ticks')
    if not math.isfinite(args.max_premium_rupees) or args.max_premium_rupees<=0 or not math.isfinite(args.tick_size_rupees) or args.tick_size_rupees<=0:p.error('Positive finite budget/tick required')
    from filelock import FileLock
    from market_lab.hilega_upstox_sandbox_execution_v1 import SandboxConfig
    from market_lab.hilega_upstox_sandbox_basket_v2 import BasketTransport,BasketWorker
    from market_lab.hilega_manual_exit_v1 import order_evidence
    cfg=SandboxConfig.from_env('.env')
    if not cfg.enabled or cfg.kill_switch or not cfg.analytics_token or not cfg.sandbox_token:
        raise SystemExit('ENABLED_SANDBOX_AND_ANALYTICS_CREDENTIALS_REQUIRED')
    ROOT.mkdir(parents=True,exist_ok=True);path=ROOT/'state.json'
    with FileLock(str(ROOT/'demo.lock'),timeout=0):
        if path.exists() and not args.resume and not args.check:raise SystemExit('EXISTING_DEMO_USE_RESUME_DO_NOT_DELETE_STATE')
        if args.resume and not path.exists():raise SystemExit('NO_DEMO_TO_RESUME')
        state=json.loads(path.read_text()) if path.exists() else dict(id=uuid.uuid4().hex[:16],started_at=now().isoformat(),sandbox_only=True)
        def persist():atomic(path,state)
        def log(kind,**values):
            row=dict(timestamp=now().isoformat(),demo_id=state['id'],kind=kind,**values)
            with (ROOT/'events.jsonl').open('a') as stream:
                stream.write(json.dumps(row)+'\n');stream.flush();os.fsync(stream.fileno())
            print(json.dumps(row),flush=True)
        if state.get('done') and not args.check:print(json.dumps(state,indent=2));return
        tr=BasketTransport(cfg.analytics_token,cfg.sandbox_token)
        try:
            if str(tr.sandbox.base_url).rstrip('/')!=HOST:raise ValueError('EXACT_SANDBOX_HOST_REQUIRED')
            if str(tr.analytics.base_url).rstrip('/')!='https://api.upstox.com':raise ValueError('ANALYTICS_HOST_MISMATCH')
            def market_quote(contract,side,quantity):
                q=tr.option_quality_quotes([contract['instrument_key']]).get(contract['instrument_key'])
                if not q:raise ValueError('FULL_QUOTE_WITH_DEPTH_REQUIRED')
                return quote_plan(q,side,quantity,args.tick_size_rupees,args.max_premium_rupees,args.cushion_ticks,now())
            if not state.get('buy'):
                # Check read-only quote/contract first. --check submits nothing
                # and does not require stopping the active Sandbox worker.
                moment=now()
                if moment.weekday()>=5 or not '09:15'<=moment.strftime('%H:%M')<'15:20':raise ValueError('RUN_DURING_REGULAR_NSE_SESSION_FOR_COMPARABLE_TEST')
                contract=next(c for c in tr.resolve_five('BULLISH',moment.date().isoformat()) if c['role']==0)
                metadata=tr._body(tr.analytics.get('/v2/option/contract',params={'instrument_key':'NSE_INDEX|Nifty 50'}))['data']
                matches=[r for r in metadata if r.get('instrument_key')==contract['instrument_key']]
                if len(matches)!=1:raise ValueError('EXACT_CURRENT_CONTRACT_METADATA_REQUIRED')
                raw=matches[0]
                if int(raw['lot_size'])!=int(contract['lot_size']) or raw['expiry']!=contract['expiry'] or raw['instrument_type']!='CE':raise ValueError('CONTRACT_IDENTITY_MISMATCH')
                raw_tick=Decimal(str(raw['tick_size']));tick=Decimal(str(args.tick_size_rupees))
                if raw_tick not in (tick,tick*100):raise ValueError('CONTRACT_TICK_DIFFERS_VERIFY_RUPEE_UNIT')
                quantity=int(contract['lot_size'])
                if quantity<=0:raise ValueError('INVALID_ONE_LOT_QUANTITY')
                plan=market_quote(contract,'BUY',quantity)
                log('READ_ONLY_PLAN',contract=contract,quantity=quantity,metadata_tick_size=str(raw_tick),
                    metadata_tick_interpretation='RUPEES' if raw_tick==tick else 'PAISE_TO_RUPEES',**plan)
                if args.check:return
                status=worker_stopped_and_flat(BasketWorker());log('STRATEGY_FLAT_WORKER_STOPPED',open_legs=status.get('open_legs'),pending=status.get('pending_fill_orders'))
                # Earlier demo files must show terminal orders and zero residual
                # before this separate probe may submit a new BUY.
                for previous_path in (Path('data/research/hilega-sandbox-demo-lifecycle-v2/state.json'),Path('data/research/hilega-sandbox-old-zip-demo/state.json')):
                    if not previous_path.exists():continue
                    prior=json.loads(previous_path.read_text());prior_contract=prior.get('contract') or {}
                    bought=sold=0
                    for side in ('BUY','SELL'):
                        record=prior.get(side.lower())
                        if not record:continue
                        if not record.get('order_id'):raise ValueError('PREVIOUS_DEMO_SUBMISSION_UNCERTAIN')
                        evidence_source='PROVIDER_ORDER_DETAILS'
                        try:
                            detail=tr.order_details(order_id=record['order_id'])
                        except Exception as exc:
                            # Historical 404 is acceptable only with saved,
                            # matching, terminal zero-fill evidence.
                            saved=record.get('evidence') or {}
                            safe=(
                                prior.get('done') is True
                                and saved.get('terminal') is True
                                and str(saved.get('order_id'))==str(record['order_id'])
                                and str(saved.get('status','')).lower() in ('cancelled','rejected')
                                and type(saved.get('filled')) is int
                                and saved['filled']==0
                                and type(saved.get('pending')) is int
                                and saved['pending']==0
                                and timestamp(record['submitted_at']).date()<now().date()
                            )
                            if 'UDAPI100010' not in str(exc) or not safe:
                                raise
                            ev=dict(saved)
                            evidence_source='SAVED_TERMINAL_ZERO_FILL_PROVIDER_404'
                        else:
                            ev=order_evidence(detail,instrument=prior_contract['instrument_key'],side=side,quantity=record['quantity'],order_id=record['order_id'])
                        log('PREVIOUS_DEMO_ORDER_EVIDENCE',side=side,evidence_source=evidence_source,**ev)
                        if not ev['terminal']:raise ValueError('PREVIOUS_DEMO_PENDING')
                        if side=='BUY':bought+=ev['filled']
                        else:sold+=ev['filled']
                    if bought!=sold:raise ValueError('PREVIOUS_DEMO_RESIDUAL_POSITION')
                state.update(contract=contract,quantity=quantity,buy_plan=plan);persist()
            elif args.check:
                print(json.dumps(dict(status='EXISTING_DEMO_READ_STATE_USE_RESUME',state=state),indent=2));return

            def submit(side,quantity):
                slot=side.lower();order=state.get(slot)
                if order:
                    if not order.get('order_id'):
                        detail=tr.order_details(tag=order['tag'])
                        ev=order_evidence(detail,instrument=state['contract']['instrument_key'],side=side,quantity=order['quantity'],tag=order['tag'])
                        order['order_id']=ev['order_id'];persist();log('UNCERTAIN_SUBMISSION_FOUND_BY_TAG',side=side,**ev)
                    return order
                if side=='BUY':worker_stopped_and_flat(BasketWorker())
                plan=market_quote(state['contract'],side,quantity)
                tag='HILLIM_'+state['id']+'_'+side
                body=dict(quantity=quantity,product='I',validity='DAY',price=plan['limit_price'],tag=tag,
                          instrument_token=state['contract']['instrument_key'],order_type='LIMIT',transaction_type=side,
                          disclosed_quantity=0,trigger_price=0,is_amo=False,slice=False)
                order=dict(tag=tag,quantity=quantity,submitted_at=now().isoformat(),plan=plan)
                state[slot]=order;persist();log('SUBMIT_INTENT',side=side,payload=body,quote_plan=plan)
                response=tr._body(tr.sandbox.post('/v3/order/place',json=body));ids=(response.get('data') or {}).get('order_ids') or []
                if len(ids)!=1:raise ValueError('AMBIGUOUS_ACK_RECONCILE_SAVED_TAG_NO_RESUBMIT')
                order['order_id']=str(ids[0]);persist();log('ACKNOWLEDGED',side=side,order_id=order['order_id'])
                return order

            def monitor(side,order):
                while True:
                    ev=order_evidence(tr.order_details(order_id=order['order_id']),instrument=state['contract']['instrument_key'],side=side,quantity=order['quantity'],order_id=order['order_id'])
                    if ev['filled']<order.get('evidence',{}).get('filled',0):raise ValueError('FILLED_QUANTITY_REGRESSED')
                    order['evidence']=ev;persist();log('ORDER_EVIDENCE',side=side,**ev)
                    if ev['terminal']:trace(tr,order,log);return ev
                    elapsed=(now()-datetime.fromisoformat(order['submitted_at'])).total_seconds()
                    if order.get('cancel_requested_at'):
                        if (now()-datetime.fromisoformat(order['cancel_requested_at'])).total_seconds()>=30:raise ValueError('CANCEL_NOT_TERMINAL_RESUME_RECONCILIATION_REQUIRED')
                    elif elapsed>=args.timeout_seconds:
                        order['cancel_requested_at']=now().isoformat();persist();log('TIMEOUT_CANCEL_REQUEST',side=side,order_id=order['order_id'])
                        tr.cancel_order(order['order_id'])
                    time.sleep(5)

            buy=monitor('BUY',submit('BUY',state['quantity']))
            if not buy['filled']:
                state.update(done=True,verdict='LIMIT_BUY_TERMINAL_ZERO_FILL',demo_remaining_quantity=0,pnl_rupees=0)
                persist();log('RESULT',verdict=state['verdict'],buy_status=buy['status'],demo_remaining_quantity=0,pnl_rupees=0);return
            sell=monitor('SELL',submit('SELL',buy['filled']))
            remaining=buy['filled']-sell['filled'];state['demo_remaining_quantity']=remaining;persist()
            if remaining:raise ValueError('DEMO_RESIDUAL_POSITION_NO_DUPLICATE_SELL: '+str(remaining))
            pnl=buy['filled']*(sell['average_price']-buy['average_price'])
            positions=position_check(tr,state['contract']['instrument_key'],log)
            state['provider_position_check']=positions;persist()
            if positions['flat'] is False:raise ValueError('FILLS_NET_ZERO_BUT_PROVIDER_POSITION_NOT_FLAT_RECONCILE')
            state.update(done=True,verdict='LIMIT_BUY_SELL_FILLS_VERIFIED',pnl_rupees=pnl,costs_included=False,
                         account_positions_independently_verified=positions['flat'] is True)
            persist();log('RESULT',verdict=state['verdict'],demo_remaining_quantity=0,pnl_rupees=pnl,
                          costs_included=False,account_positions_independently_verified=positions['flat'] is True)
        except Exception as exc:
            log('STOPPED_RECONCILIATION_REQUIRED',error_type=type(exc).__name__,error=str(exc),
                instruction='Use --resume for existing order reconciliation; do not delete state or restart trading with unresolved demo exposure.')
            raise SystemExit(1)
        finally:tr.close()


class Checks(unittest.TestCase):
    def detail(self,**updates):
        row=dict(order_id='TEST',instrument_token='NSE_FO|TEST',transaction_type='BUY',product='I',
                 quantity=65,filled_quantity=0,pending_quantity=0,status='open pending',average_price=0)
        row.update(updates);return row
    def evidence(self,row):
        from market_lab.hilega_manual_exit_v1 import order_evidence
        return order_evidence(row,instrument='NSE_FO|TEST',side='BUY',quantity=65,order_id='TEST')
    def test_ack_not_a_fill(self):
        e=self.evidence(self.detail());self.assertFalse(e['terminal']);self.assertEqual(e['filled'],0)
    def test_cancel_can_contain_partial_fill(self):
        e=self.evidence(self.detail(status='cancelled',filled_quantity=32,average_price=100))
        self.assertTrue(e['terminal']);self.assertEqual(e['filled'],32)
    def test_complete_requires_full_fill(self):
        with self.assertRaises(ValueError):self.evidence(self.detail(status='complete',filled_quantity=0))
    def test_fill_requires_average_price(self):
        with self.assertRaises(ValueError):self.evidence(self.detail(status='complete',filled_quantity=65,average_price=0))
    def test_identity_mismatch_rejected(self):
        with self.assertRaises(ValueError):self.evidence(self.detail(instrument_token='NSE_FO|OTHER'))
    def q(self):return dict(bid_price=100,ask_price=100.1,bid_quantity=65,ask_quantity=65,quote_time=now().isoformat())
    def test_buy_limit_above_ask(self):self.assertEqual(quote_plan(self.q(),'BUY',65,.05,15000,2,now())['limit_price'],100.2)
    def test_sell_limit_below_bid(self):self.assertEqual(quote_plan(self.q(),'SELL',65,.05,15000,2,now())['limit_price'],99.9)
    def test_depth_rejected(self):
        q=self.q();q['ask_quantity']=0
        with self.assertRaises(ValueError):quote_plan(q,'BUY',65,.05,15000,2,now())
    def test_stale_rejected(self):
        q=self.q();q['quote_time']=(now()-timedelta(seconds=20)).isoformat()
        with self.assertRaises(ValueError):quote_plan(q,'BUY',65,.05,15000,2,now())
    def test_budget_rejected(self):
        with self.assertRaises(ValueError):quote_plan(self.q(),'BUY',65,.05,100,2,now())
    def test_spread_rejected(self):
        q=self.q();q['ask_price']=120
        with self.assertRaises(ValueError):quote_plan(q,'BUY',65,.05,15000,2,now())
    def test_timestamp_epoch_ms(self):self.assertAlmostEqual(timestamp(now().timestamp()*1000).timestamp(),now().timestamp(),delta=1)


if __name__=='__main__':main()
