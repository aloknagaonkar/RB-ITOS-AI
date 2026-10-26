"""Read-only account pin and snapshot CLI. No trading controls or orders."""
import argparse,getpass,hmac,json,os,sys
from pathlib import Path
from dotenv import load_dotenv
from market_lab.hilega_production_account_adapter_v1 import (
    AdapterBlocked,Client,utcnow,profile_id,enroll,read_pin,capture,verify,save_capture)

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--env-file',type=Path,default=Path('.env'))
    parser.add_argument('--pin-file',type=Path,default=Path.home()/'hilega-private/upstox-account-pin.json')
    parser.add_argument('--snapshot-file',type=Path,default=Path('data/research/hilega-production-account-adapter/latest.json'))
    parser.add_argument('action',choices=['enroll','snapshot','verify'])
    a=parser.parse_args()
    try:
        if a.action=='verify':
            pin=read_pin(a.pin_file)
            if a.snapshot_file.stat().st_size>8_000_000:raise AdapterBlocked('SNAPSHOT_TOO_LARGE')
            result=verify(json.loads(a.snapshot_file.read_text()),pin,as_of=utcnow().isoformat())
            print(json.dumps(dict(result,orders_sent=False)));return 0
        load_dotenv(a.env_file,override=False)
        token=os.getenv('HILEGA_PRODUCTION_BROKER_READ_TOKEN') or os.getenv('UPSTOX_ACCESS_TOKEN','')
        client=Client(token)
        if a.action=='enroll':
            if a.pin_file.exists() or a.pin_file.is_symlink():raise AdapterBlocked('ACCOUNT_PIN_EXISTS_NO_OVERWRITE')
            if not sys.stdin.isatty():raise AdapterBlocked('INTERACTIVE_TERMINAL_REQUIRED_FOR_ENROLLMENT')
            before=client.get('profile');uid=profile_id(before)
            print('Read-only account pin enrollment. Verify your Upstox User ID in your broker account.')
            print('Enter it privately below. No account ID, profile details or token will be saved or printed.')
            expected=getpass.getpass('Expected Upstox User ID (hidden): ').strip()
            if not hmac.compare_digest(expected.encode(),uid.encode()):raise AdapterBlocked('EXPECTED_ACCOUNT_DOES_NOT_MATCH_PROFILE')
            after=client.get('profile')
            if not hmac.compare_digest(profile_id(after).encode(),uid.encode()):raise AdapterBlocked('PROFILE_CHANGED_DURING_ENROLLMENT')
            enroll(a.pin_file,after,expected,at=utcnow().isoformat())
            print(json.dumps(dict(status='ACCOUNT_PIN_CREATED',account_identity_verified=True,
                production_execution_enabled=False,orders_sent=False)));return 0
        pin=read_pin(a.pin_file);report=capture(client,pin);save_capture(report,a.snapshot_file,a.pin_file)
        summary={k:report.get(k) for k in ('status','reason','account_identity_verified','generated_at','completed_at','diagnostics','production_execution_enabled','orders_sent','entry_permission')}
        summary['counts']={n:len(report[n]) if isinstance(report.get(n),list) else None for n in ('orders','trades','positions')}
        print(json.dumps(summary,indent=2));return 0 if report['status']=='READ_ONLY_CAPTURED' else 2
    except AdapterBlocked as exc:
        print(json.dumps(dict(status='BLOCKED',reason=str(exc),production_execution_enabled=False,orders_sent=False)));return 2
    except (KeyboardInterrupt,EOFError):
        print(json.dumps(dict(status='CANCELLED',orders_sent=False)));return 130
    except Exception as exc:
        print(json.dumps(dict(status='BLOCKED',reason='LOCAL_OR_TRANSPORT_ERROR',error_type=type(exc).__name__,orders_sent=False)));return 2
if __name__=='__main__':raise SystemExit(main())
