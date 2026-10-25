"""Confirmed strategy signals into simulated orders only. No Upstox transport."""
import argparse,json,os,time,uuid
from datetime import datetime,timedelta
from pathlib import Path
from market_lab.hilega_production_foundation.core import Store,SimBroker,Service,Blocked
from market_lab.hilega_production_simulator_bridge_v1 import Bridge,POLICY,VERSION

BULL='ENTRY_PATH1_ROUTE_A_CROSS_RSI50_ABOVE_WMA21';BEAR='ENTRY_BEARISH_ROUTE_B_STRUCTURAL'
BX='STRUCTURAL_EXIT_RSI_CROSS_BELOW_WMA21';SX='STRUCTURAL_EXIT_BEARISH_RSI_CROSS_ABOVE_WMA21'
def stamp(t):return '2026-10-25T'+t+':00+05:30'
def event(t,names,ref='09:25'):
    return dict(stage='DIRECTIONAL_DECISION',status='PROCESSED',payload=dict(policy_id=POLICY,strategy_version=VERSION,
        reconstructed=False,decision_timestamp=stamp(t),accepted_events=names,event_details=[dict(event_type=n,event_time=stamp(t),
        entry_time=stamp(t) if n in {BULL,BEAR} else stamp(ref),qualified_signal_time=None) for n in names]))
def command(s,action,**kw):
    c=s.status()['control'];return s.command(action,request_id=str(uuid.uuid4()),expected_version=c['version'],session_date=c['session_date'],actor='synthetic-demo',**kw)
def demo(output):
    if output.exists():raise Blocked('DEMO_OUTPUT_EXISTS_USE_NEW_DIRECTORY')
    output.mkdir(parents=True,mode=0o700)
    clock=[datetime.fromisoformat(stamp('09:24'))+timedelta(seconds=59)]
    store=Store(output/'simulation.sqlite');broker=SimBroker(store);s=Service(store,broker,lambda:clock[0])
    bridge=Bridge(s,output/'ownership-fixture.sqlite',auto_fill_entries=True)
    command(s,'reconcile');command(s,'resume');clock[0]=datetime.fromisoformat(stamp('09:25'))
    stages=[]
    def note(label):
        proof=bridge.poll();orders=broker.orders()
        stages.append(dict(stage=label,control=s.status()['control']['mode'],buy_orders=sum(o['side']=='BUY' for o in orders),
            sell_orders=sum(o['side']=='SELL' for o in orders),simulator_positions=broker.positions(),
            ownership_status=proof['status'],production_execution_enabled=False))
    bridge.process(event('09:25',['PATH1_ARMED_RSI_CROSS_EMA3_UP']));note('Armed only: no BUY')
    bridge.process(event('09:25',[BULL]));note('Confirmed bullish: simulated BUY')
    clock[0]=datetime.fromisoformat(stamp('09:30'));broker.auto_fill_sells=False
    bridge.process(event('09:30',[BX,BEAR]));note('SELL pending: opposite BUY waits')
    command(s,'pause');clock[0]+=timedelta(seconds=10)
    sell=next(i for i in store.intents() if i['side']=='SELL');broker.fill(sell['id'],65,100)
    note('Pause during reversal: SELL finishes; BUY blocked')
    command(s,'reconcile');command(s,'resume');clock[0]=datetime.fromisoformat(stamp('09:35'));broker.auto_fill_sells=True
    bridge.process(event('09:35',[BEAR]));note('Resume: next fresh bearish entry')
    clock[0]=datetime.fromisoformat(stamp('09:40'));bridge.process(event('09:40',[SX,BULL],ref='09:35'));note('Immediate reversal: SELL filled before BUY')
    clock[0]=datetime.fromisoformat(stamp('09:41'));entry=next(i for i in store.intents() if i['side']=='BUY' and s._remaining(i)[0])
    command(s,'exit',position_id=entry['id']);note('Manual simulator exit: flat and PAUSED')
    ok=(stages[0]['buy_orders']==0 and stages[2]['buy_orders']==1 and stages[3]['buy_orders']==1 and
        stages[4]['buy_orders']==2 and stages[5]['buy_orders']==3 and not any(broker.positions().values()) and
        all(x['ownership_status']=='RECONCILED_OFFLINE_FIXTURE' for x in stages))
    report=dict(status='PASS' if ok else 'FAIL',stages=stages,bridge_events=bridge.rows(),control=s.status(),
        ownership=bridge.ledger.report(as_of=s.now().isoformat()),simulated_executions=broker.fills(),
        evidence_mode='SYNTHETIC_SIMULATOR_DEMO',orders_sent_to_upstox=False,production_execution_enabled=False)
    (output/'report.json').write_text(json.dumps(report,indent=2))
    lines=['# Strategy -> controls -> simulator -> ownership','',
        'Synthetic option prices and fills only. No actual strategy replay or Upstox requests.','',
        '| Stage | Control | BUY orders | SELL orders | Ownership audit |','|---|---|---:|---:|---|']
    lines+=['| '+x['stage']+' | '+x['control']+' | '+str(x['buy_orders'])+' | '+str(x['sell_orders'])+' | '+x['ownership_status']+' |' for x in stages]
    lines+=['','Result: '+report['status'],'Production execution enabled: false']
    text='\n'.join(lines)+'\n';(output/'summary.md').write_text(text);print(text);return 0 if ok else 1

def main():
    p=argparse.ArgumentParser(description=__doc__);group=p.add_mutually_exclusive_group(required=True)
    group.add_argument('--demo',action='store_true');group.add_argument('--once',action='store_true');group.add_argument('--watch',action='store_true')
    p.add_argument('--output',type=Path);p.add_argument('--env-file',type=Path,default=Path('.env'))
    p.add_argument('--source',type=Path,default=Path('data/live-observation/hilega-directional-v1/step-audit.jsonl'))
    p.add_argument('--synthetic-fills',action='store_true',help='Explicit fake entry fills; never actual execution or live P&L')
    a=p.parse_args()
    if a.demo:
        if not a.output:p.error('--demo requires a new --output directory')
        return demo(a.output)
    from dotenv import load_dotenv
    load_dotenv(a.env_file,override=False)
    if os.getenv('HILEGA_PRODUCTION_WORKSPACE_MODE')!='SIMULATION_ONLY' or os.getenv('HILEGA_PRODUCTION_SIM_BRIDGE_ENABLED','0')!='1':raise Blocked('SIMULATION_MODE_AND_EXPLICIT_BRIDGE_OPT_IN_REQUIRED')
    from market_lab.hilega_combined_policy_v1 import POLICY_ID,VERSION as installed
    if (POLICY_ID,installed)!=(POLICY,VERSION):raise Blocked('INSTALLED_STRATEGY_VERSION_MISMATCH')
    store=Store(Path(os.getenv('HILEGA_PRODUCTION_SIM_DB','data/research/hilega-production-workspace/sim.sqlite')))
    s=Service(store,SimBroker(store)) # durable startup pause; never auto-arm
    bridge=Bridge(s,Path(str(store.path)+'.ownership-fixture.sqlite'),auto_fill_entries=a.synthetic_fills)
    try:
        while True:
            print(json.dumps(bridge.run_source_once(a.source)),flush=True)
            if a.once:return 0
            time.sleep(5)
    finally:
        bridge.stop('SIM_BRIDGE_PROCESS_STOPPED')
if __name__=='__main__':
    try:raise SystemExit(main())
    except Blocked as exc:
        print(json.dumps(dict(status='BLOCKED',reason=str(exc),production_execution_enabled=False,orders_sent_to_upstox=False)));raise SystemExit(2)
    except KeyboardInterrupt:raise SystemExit(130)
    except Exception as exc:
        print(json.dumps(dict(status='BLOCKED',error_type=type(exc).__name__,production_execution_enabled=False,orders_sent_to_upstox=False)));raise SystemExit(2)
