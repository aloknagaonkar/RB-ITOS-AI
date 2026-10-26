"""Assess existing local records only; no network, token access, apply or restart."""
import argparse
import json
from pathlib import Path
from link import assess, AssessmentJournal, Blocked
from market_lab.hilega_production_account_adapter_v1 import read_pin, utcnow, day


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--controller-db',type=Path,required=True)
    parser.add_argument('--adapter-db',type=Path,required=True)
    parser.add_argument('--review-dir',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--pin-file',type=Path,default=Path.home()/'hilega-private/upstox-account-pin.json')
    args = parser.parse_args()
    try:
        pin = read_pin(args.pin_file)
        now = utcnow()
        source_paths = [args.controller_db,args.adapter_db,args.review_dir/'evidence.sqlite3',args.pin_file]
        journal = AssessmentJournal(args.output,pin,day(now),source_paths=source_paths)
        result = assess(args.controller_db,args.adapter_db,args.review_dir,pin,as_of=now.isoformat())
        result = journal.record(result)
        # Private IDs, symbols, fingerprints and fills stay in the dedicated local audit.
        public = {k:v for k,v in result.items() if k not in {'links','snapshot_id','capture_fingerprint'}}
        public['linked_request_count'] = len(result['links'])
        public['linked_fill_count'] = sum(x['fill_count'] for x in result['links'])
        print(json.dumps(public))
        return 0 if result['status'] == 'LOCAL_CHAIN_CONSISTENT_AUTHORITY_NOT_GRANTED' else 2
    except Exception as exc:
        reason = str(exc) if isinstance(exc,Blocked) else 'LOCAL_INPUT_OR_STORAGE_ERROR'
        print(json.dumps(dict(status='BLOCKED',reason=reason,orders_sent=False,
                              production_execution_enabled=False)))
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
