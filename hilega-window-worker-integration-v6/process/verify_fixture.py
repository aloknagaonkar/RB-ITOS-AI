"""Verify synthetic signed reservation without broker transport."""
import argparse,json,sqlite3,sys
from pathlib import Path
from fixture_clock import now
from window import need

def main():
    p=argparse.ArgumentParser();p.add_argument('--bundle',type=Path,required=True);p.add_argument('--workspace',type=Path,required=True);a=p.parse_args();now(a.workspace)
    sys.path[:0]=[str(a.bundle/'backend'),str(a.bundle/'runtime')]
    from market_lab.hilega_preparation_runtime_v1.cash_reservation import verify_row
    from hilega_application_preparation_fixtures import PIN
    db=sqlite3.connect((a.workspace/'application.sqlite').as_uri()+'?mode=ro',uri=True)
    try:
        rows=[json.loads(x[0]) for x in db.execute('SELECT data FROM preparation_cash_reservations')]
        need(len(rows)==1,'SINGLE_RESERVATION_REQUIRED');verify_row(rows[0],PIN)
    finally:db.close()
    from market_lab.hilega_production_account_adapter_v1 import sign
    import hmac
    boundary=json.loads((a.workspace/'WORKER-SEED-BOUNDARY.json').read_text());signature=boundary.pop('signature',None)
    need(isinstance(signature,str) and hmac.compare_digest(signature,sign(boundary,PIN)),'SIGNED_WORKER_SEED_BOUNDARY_REQUIRED')
    need(boundary['controller_paused'] is True and boundary['owner_enrolled'] is False and boundary['production_execution_enabled'] is False,'DISABLED_WORKER_BOUNDARY_REQUIRED')

if __name__=='__main__':main()
