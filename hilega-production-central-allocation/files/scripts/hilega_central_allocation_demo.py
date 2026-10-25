"""Synthetic single-leg strategy bridge through central allocation gate."""
import argparse,json,os
from pathlib import Path
from datetime import datetime,timedelta
from market_lab.hilega_production_foundation.core import Store,Service,SimBroker
from market_lab.hilega_sim_allocation_v1 import synthetic_funds
from market_lab.hilega_production_simulator_bridge_v1 import Bridge,POLICY,VERSION
from uuid import uuid4

def main():
    p=argparse.ArgumentParser();p.add_argument('--output',type=Path,required=True);a=p.parse_args()
    if a.output.exists():raise ValueError('USE_NEW_OUTPUT_DIRECTORY')
    a.output.mkdir(parents=True,mode=0o700);os.environ['HILEGA_PRODUCTION_WORKSPACE_MODE']='SIMULATION_ONLY';os.environ['HILEGA_PRODUCTION_SIM_BRIDGE_ENABLED']='0'
    clock=[datetime.fromisoformat('2026-10-26T09:24:59+05:30')];store=Store(a.output/'sim.sqlite');broker=SimBroker(store)
    s=Service(store,broker,lambda:clock[0]);synthetic_funds(s,'100000')
    def command(action):
        c=s.status()['control'];return s.command(action,request_id=str(uuid4()),expected_version=c['version'],session_date=c['session_date'],actor='SYNTHETIC_DEMO')
    command('reconcile');command('resume');bridge=Bridge(s,a.output/'ownership.sqlite',auto_fill_entries=True);stages=[]
    def event(names,ref=None):
        at=clock[0].isoformat()
        return dict(stage='DIRECTIONAL_DECISION',status='PROCESSED',payload=dict(policy_id=POLICY,strategy_version=VERSION,reconstructed=False,
            decision_timestamp=at,accepted_events=names,event_details=[dict(event_type=n,event_time=at,entry_time=ref if n.startswith('STRUCTURAL_EXIT') else at) for n in names]))
    def note(name):
        a=s.status()['allocation'];stages.append(dict(stage=name,held=a['held_total'],orders=len(broker.orders()),control=s.status()['control']['mode']))
    clock[0]+=timedelta(seconds=1);first=clock[0].isoformat()
    bridge.process(event(['ENTRY_PATH1_ROUTE_A_CROSS_RSI50_ABOVE_WMA21']));note('Confirmed bullish uses central reservation')
    clock[0]+=timedelta(minutes=5);synthetic_funds(s,'100000');bridge.poll()
    bridge.process(event(['STRUCTURAL_EXIT_RSI_CROSS_BELOW_WMA21','ENTRY_BEARISH_ROUTE_B_STRUCTURAL'],first));note('Reversal SELL releases old hold before bearish BUY reserves')
    command('pause');note('Pause keeps established bearish hold')
    clock[0]+=timedelta(minutes=5);bridge.process(event(['STRUCTURAL_EXIT_BEARISH_RSI_CROSS_ABOVE_WMA21'],(clock[0]-timedelta(minutes=5)).isoformat()));note('Exit works with stale funds; releases after flat')
    fills=broker.fills();ok=[x['side'] for x in fills]==['BUY','SELL','BUY','SELL'] and [x['held'] for x in stages]==['6600.00','6600.00','6600.00','0.00']
    report=dict(status='PASS' if ok else 'FAIL',stages=stages,allocation=s.status()['allocation'],fills=fills,production_execution_enabled=False,orders_sent=False)
    (a.output/'report.json').write_text(json.dumps(report,indent=2))
    text='# Central simulator allocation\n\nSynthetic cash and fills. No Upstox requests.\n\n| Stage | Held INR | Orders | Control |\n|---|---:|---:|---|\n'
    text+=''.join('| '+x['stage']+' | '+x['held']+' | '+str(x['orders'])+' | '+x['control']+' |\n' for x in stages)
    text+='\nResult: '+report['status']+'\n';(a.output/'summary.md').write_text(text);print(text);return 0 if ok else 2
if __name__=='__main__':raise SystemExit(main())
