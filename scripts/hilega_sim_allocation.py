"""Local simulator cash fixture update; never resumes or reads Upstox funds."""
import argparse,json,os
from pathlib import Path
from dotenv import load_dotenv
from market_lab.hilega_production_foundation.core import Store,Service,SimBroker,Blocked
from market_lab.hilega_sim_allocation_v1 import synthetic_funds

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--env-file',type=Path,default=Path('.env'))
    p.add_argument('--cash',required=True);p.add_argument('--confirm-synthetic-cash',action='store_true');a=p.parse_args()
    if not a.confirm_synthetic_cash:p.error('Explicit --confirm-synthetic-cash required')
    load_dotenv(a.env_file,override=False)
    if os.getenv('HILEGA_PRODUCTION_WORKSPACE_MODE')!='SIMULATION_ONLY':raise Blocked('SIMULATION_ONLY_MODE_REQUIRED')
    store=Store(Path(os.getenv('HILEGA_PRODUCTION_SIM_DB','data/research/hilega-production-workspace/sim.sqlite')))
    s=Service(store,SimBroker(store),worker_start=False)
    print(json.dumps(dict(allocation=synthetic_funds(s,a.cash),control=s.status()['control'],orders_sent=False),indent=2))
if __name__=='__main__':
    try:main()
    except Blocked as exc:print(json.dumps(dict(status='BLOCKED',reason=str(exc),orders_sent=False)));raise SystemExit(2)
