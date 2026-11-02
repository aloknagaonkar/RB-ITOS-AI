"""Bounded registration probe. Does not instantiate Source, Store, providers or sessions."""
import argparse
import json
from pathlib import Path
import sys


def main():
    p=argparse.ArgumentParser();p.add_argument('--registration',type=Path,required=True);p.add_argument('--sha256',required=True)
    a=p.parse_args();root=Path(__file__).resolve().parent
    sys.path.insert(0,str(root/'backend'));sys.path.insert(0,str(root/'runtime'))
    from market_lab.hilega_worker_registration_v1 import load_closed_registration,ClosedRegistration
    value=load_closed_registration(a.registration,a.sha256)
    if type(value) is not ClosedRegistration:raise ValueError('EXACT_CLOSED_PROBE_REQUIRED')
    from closed_application_coordinator_v1 import worker_tick
    result=worker_tick()
    if result['production_execution_enabled'] is not False or result['application_database_opened'] is not False:
        raise ValueError('PROBE_MUST_REMAIN_CLOSED')
    print(json.dumps(dict(status='MANAGED_CLOSED_REGISTRATION_PROBE_PASS',application_database_opened=False,
        credentials_opened=False,source_worker_executed=False,production_execution_enabled=False)))
    return 0

if __name__=='__main__':raise SystemExit(main())
