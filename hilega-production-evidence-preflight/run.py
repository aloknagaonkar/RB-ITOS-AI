"""Fresh GET-only evidence collection and read-only controller preflight."""
import argparse
import json
import os
import re
from pathlib import Path
from dotenv import dotenv_values
from evidence import evaluate,validate,Blocked,FLAGS,dependencies
from collect import capture
from market_lab.hilega_production_account_adapter_v1 import read_pin,utcnow


def save(path,value):
    fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
    with os.fdopen(fd,'w') as stream:
        json.dump(value,stream,indent=2);stream.flush();os.fsync(stream.fileno())


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--env-file',type=Path,default=Path('.env'))
    parser.add_argument('--pin-file',type=Path,default=Path.home()/'hilega-private/upstox-account-pin.json')
    parser.add_argument('--controller-db',type=Path,default=Path('data/research/hilega-production-workspace/sim.sqlite'))
    parser.add_argument('--adapter-db',type=Path,default=Path('data/research/hilega-broker-adapter-closed/adapter.sqlite'))
    parser.add_argument('--capture-only',action='store_true',help='No signal or controller admission check; collect evidence only')
    parser.add_argument('--direction',choices=['BULLISH','BEARISH'])
    parser.add_argument('--expected-version',type=int)
    parser.add_argument('--bridge-run-id')
    parser.add_argument('--signal-at',help='Actual signal time with timezone; never invent a strategy signal')
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    admission=(args.direction,args.expected_version,args.bridge_run_id,args.signal_at)
    if args.capture_only and any(x is not None for x in admission):
        parser.error('--capture-only cannot be combined with admission arguments')
    if not args.capture_only and any(x is None for x in admission):
        parser.error('provide --capture-only or all admission arguments')
    created_output=False
    try:
        dependencies()
        if args.output.exists():raise Blocked('FRESH_OUTPUT_DIRECTORY_REQUIRED')
        output=args.output.resolve()
        for source in (args.controller_db,args.adapter_db,args.pin_file,args.env_file):
            if Path(source).resolve().is_relative_to(output):raise Blocked('OUTPUT_CONTAINS_SOURCE_OR_CREDENTIAL_FILE')
        config=dotenv_values(args.env_file)
        def setting(name):
            shell=os.environ.get(name);file=config.get(name)
            if shell and file and shell!=file:raise Blocked('SHELL_ENV_FILE_TOKEN_CONFLICT')
            return shell or file
        # Resolve BOTH variables so an unused conflicting alternate also blocks.
        primary=setting('HILEGA_PRODUCTION_BROKER_READ_TOKEN')
        secondary=setting('UPSTOX_ACCESS_TOKEN')
        token=(primary or secondary or '').strip()
        if not token:raise Blocked('READ_TOKEN_MISSING')
        pin=read_pin(args.pin_file)
        args.output.mkdir(parents=True,mode=0o700)
        created_output=True
        bundle=capture(token,pin)
        save(args.output/'evidence.json',bundle)
        now=utcnow().isoformat()
        if args.capture_only:
            plans=validate(bundle,pin,as_of=now)
            reasons=sorted({r for plan in plans for r in plan['reasons']})
            result=dict(FLAGS,status='READ_ONLY_EVIDENCE_CHECKS_PASS' if not reasons else 'NOT_CLEARED',
                reasons=reasons,controller_checks_performed=False,production_ready=False,
                preparation_preview=plans,thresholds_approved_for_production=False,
                debit_attribution='NOT_VALIDATED',assessed_at=now)
        else:
            result=evaluate(bundle,pin,direction=args.direction,as_of=now,
                controller_db=args.controller_db,adapter_db=args.adapter_db,
                expected_version=args.expected_version,bridge_run_id=args.bridge_run_id,signal_at=args.signal_at)
        save(args.output/'report.json',result)
        safe={k:v for k,v in result.items() if k not in {'preparation_preview','controls'}}
        print(json.dumps(safe),flush=True)
        return 0 if result['status'] in {'READ_ONLY_PREFLIGHT_CHECKS_PASS','READ_ONLY_EVIDENCE_CHECKS_PASS'} else 2
    except Exception as exc:
        reason=str(exc) if isinstance(exc,ValueError) and re.fullmatch(r'[A-Z0-9_]{1,120}',str(exc)) else 'LOCAL_OR_CAPTURE_ERROR'
        result=dict(status='BLOCKED',reasons=[reason],**FLAGS)
        # A fresh failure never presents an old successful report as current evidence.
        if created_output and args.output.is_dir() and not (args.output/'report.json').exists():
            try:save(args.output/'report.json',result)
            except OSError:pass
        print(json.dumps(result),flush=True)
        return 2


if __name__=='__main__':
    raise SystemExit(main())
