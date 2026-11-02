"""VM-only contract checks against the deployed journal validator before a worker is launched."""
import argparse,copy,json,sys
from pathlib import Path
from fixture_records import entry_payload
from window import need

def main():
    p=argparse.ArgumentParser();p.add_argument('--bundle',type=Path,required=True);a=p.parse_args()
    sys.dont_write_bytecode=True;sys.path[:0]=[str(a.bundle/'backend'),str(a.bundle/'runtime')]
    from market_lab.hilega_production_simulator_bridge_v1 import accepted
    row=dict(sequence=2,record_hash='synthetic-contract-only',stage='DIRECTIONAL_DECISION',status='PROCESSED',payload=entry_payload('2026-10-26T09:30:00+05:30'))
    result=accepted(row);need(len(result)==1 and result[0]['role']=='ENTRY','FIXTURE_VALID_ENTRY_NOT_ACCEPTED')
    bad=copy.deepcopy(row);bad['payload'].pop('reconstructed')
    try:accepted(bad)
    except Exception as exc:need(str(exc)=='SOURCE_RECONSTRUCTION_FLAG_REQUIRED','UNEXPECTED_RECONSTRUCTION_CHECK')
    else:raise ValueError('MISSING_RECONSTRUCTION_FLAG_WAS_ACCEPTED')
    bad=copy.deepcopy(row);bad['payload']['decision_timestamp']='2026-10-26T09:30:01+05:30'
    try:accepted(bad)
    except Exception as exc:need(str(exc)=='COMPLETED_FIVE_MINUTE_BOUNDARY_REQUIRED','UNEXPECTED_BOUNDARY_CHECK')
    else:raise ValueError('NON_BOUNDARY_SIGNAL_WAS_ACCEPTED')
    print(json.dumps(dict(status='BUNDLED_SIGNAL_SCHEMA_CONTRACT_PASS',cases=3)));return 0
if __name__=='__main__':raise SystemExit(main())
