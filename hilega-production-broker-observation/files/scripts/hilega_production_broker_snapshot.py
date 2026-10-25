"""One GET-only broker snapshot; no order transport or strategy imports."""
import argparse,json,os
from pathlib import Path
from dotenv import load_dotenv
from market_lab.hilega_production_broker_observation_v1 import Client,collect,write_snapshot

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--env-file',type=Path,default=Path('.env'))
    p.add_argument('--output',type=Path,default=Path('data/research/hilega-production-broker-observation/latest.json'))
    a=p.parse_args();load_dotenv(a.env_file,override=False)
    try:
        token=os.getenv('HILEGA_PRODUCTION_BROKER_READ_TOKEN') or os.getenv('UPSTOX_ACCESS_TOKEN','')
        s=collect(Client(token).get);write_snapshot(s,a.output)
        print(json.dumps(dict(status=s['connection_status'],checks=[dict(check=n,status=c['status'],error=c.get('error'),provider_code=c.get('provider_code')) for n,c in s['checks'].items()],diagnostics=s['diagnostics'],orders_sent=False,production_execution_enabled=False)))
        return 0 if s['connection_status']=='PASS' else 2
    except Exception as e:
        print(json.dumps(dict(status='FAIL',error_type=type(e).__name__,orders_sent=False)));return 2
if __name__=='__main__':raise SystemExit(main())
