"""Capture and review signed Upstox account evidence using existing GET-only adapter."""
import argparse
import hashlib
import json
import os
import time
from pathlib import Path


def dependencies():
    root = Path(__file__).resolve().parent.parent
    expected = json.loads(Path(__file__).with_name('dependencies.json').read_text())
    for name, digest in expected.items():
        p = root/name
        if not p.is_file() or hashlib.sha256(p.read_bytes()).hexdigest() != digest:
            raise ValueError('INSTALLED_DEPENDENCY_VERSION_MISMATCH')


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--env-file',type=Path,default=Path('.env'))
    p.add_argument('--pin-file',type=Path,default=Path.home()/'hilega-private/upstox-account-pin.json')
    p.add_argument('--output',type=Path,required=True)
    p.add_argument('--samples',type=int,default=3)
    p.add_argument('--interval',type=float,default=10)
    a = p.parse_args()
    if not 1 <= a.samples <= 60 or not 1 <= a.interval <= 60:
        p.error('samples must be 1..60 and interval 1..60 seconds')
    try:
        dependencies()
        from dotenv import dotenv_values
        from market_lab.hilega_production_account_adapter_v1 import Client,capture,read_pin,utcnow
        from review import Journal
        config = dotenv_values(a.env_file)
        for name in ('HILEGA_PRODUCTION_BROKER_READ_TOKEN','UPSTOX_ACCESS_TOKEN'):
            if os.environ.get(name) and config.get(name) and os.environ[name] != config[name]:
                raise ValueError('SHELL_FILE_TOKEN_CONFLICT')
        token = (os.environ.get('HILEGA_PRODUCTION_BROKER_READ_TOKEN') or config.get('HILEGA_PRODUCTION_BROKER_READ_TOKEN')
                 or os.environ.get('UPSTOX_ACCESS_TOKEN') or config.get('UPSTOX_ACCESS_TOKEN') or '').strip()
        if not token: raise ValueError('READ_TOKEN_MISSING')
        pin = read_pin(a.pin_file)
        journal = Journal(a.output,pin)
        client = Client(token)
        failed = False
        for i in range(a.samples):
            report = capture(client,pin)
            result = journal.record(report,as_of=utcnow().isoformat())
            # No raw user ID, token, profile or signed raw evidence on stdout.
            print(json.dumps(dict(sample=i+1,**result)),flush=True)
            failed |= result['status'] != 'READ_ONLY_REVIEWED'
            if i+1 < a.samples: time.sleep(a.interval)
        print('Read-only evidence review completed. Strategy ownership and external-exit attribution remain unverified.')
        return 2 if failed else 0
    except KeyboardInterrupt:
        return 130
    except Exception as exc:
        safe = str(exc) if isinstance(exc,ValueError) and str(exc).replace('_','').isalnum() else 'LOCAL_OR_TRANSPORT_ERROR'
        print(json.dumps(dict(status='BLOCKED',reason=safe,orders_sent=False,production_execution_enabled=False)))
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
