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
if __name__=='__main__':main()
