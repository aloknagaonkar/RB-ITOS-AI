"""Capture a pinned account and review current entry quantity without mutations."""
import argparse
from datetime import datetime,timezone
import hashlib
import json
import os
from pathlib import Path
import re
import sys
from ownership_review import reconcile_entry
from risk_evidence_audit import read_sources,regular,need,assess


def validate_package(root):
    folder=Path(__file__).resolve().parent
    manifest=json.loads(regular(folder/'manifest.json').read_text())
    for prefix,items in ((folder,manifest['package_sha256']),(root,manifest['installed_source_sha256'])):
        for name,expected in items.items():
            need(hashlib.sha256(regular(prefix/name).read_bytes()).hexdigest()==expected,
                 'PACKAGE_OR_INSTALLED_SOURCE_CHANGED')


def consistent_review(reader,provider,pin,*,clock,mode='LIVE_CLOSED',verifier=None):
    before=reader();assess(before)
    snapshot=provider()
    after=reader()
    need(before==after,'LOCAL_SOURCES_CHANGED_DURING_CAPTURE')
    return reconcile_entry(after,snapshot,pin,as_of=clock(),mode=mode,verifier=verifier)


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('action',choices=['check'])
    p.add_argument('--capture-account',action='store_true',required=True)
    p.add_argument('--repo',type=Path,default=Path.cwd())
    p.add_argument('--pin-file',type=Path,default=Path.home()/'hilega-private/upstox-account-pin.json')
    args=p.parse_args();root=args.repo.resolve();validate_package(root)
    sys.path.insert(0,str(root/'backend'))
    from market_lab.hilega_production_account_adapter_v1 import read_pin,capture,Client,verify
    from dotenv import dotenv_values
    pin=read_pin(args.pin_file)
    need(re.fullmatch(r'UPSTOX:[0-9a-f]{64}',pin['scope']) is not None,'LIVE_UPSTOX_PIN_SCOPE_REQUIRED')
    app=root/'data/research/hilega-production-workspace/sim.sqlite'
    adapter=root/'data/research/hilega-broker-adapter-closed/adapter.sqlite'
    settings=dotenv_values(root/'.env')
    def setting(name):
        shell,file=os.getenv(name),settings.get(name)
        need(not(shell and file and shell!=file),'TOKEN_CONFIGURATION_CONFLICT')
        return shell or file
    primary=setting('HILEGA_PRODUCTION_BROKER_READ_TOKEN')
    secondary=setting('UPSTOX_ACCESS_TOKEN')
    token=(primary or secondary or '').strip();need(bool(token),'READ_TOKEN_MISSING')
    def reader():
        need(read_pin(args.pin_file)==pin,'ACCOUNT_PIN_CHANGED_DURING_CAPTURE')
        return read_sources(app,adapter,pin['scope'])
    report=consistent_review(reader,lambda:capture(Client(token),pin),pin,
        clock=lambda:datetime.now(timezone.utc).isoformat(),verifier=verify)
    report['broker_reads_performed']=True
    print(json.dumps(report,indent=2))

if __name__=='__main__':
    try:main()
    except Exception as exc:
        reason=str(exc)
        print(json.dumps(dict(status='STOPPED_FOR_REVIEW',
            reason=reason if re.fullmatch(r'[A-Z][A-Z0-9_]{0,179}',reason) else type(exc).__name__,
            production_execution_enabled=False,entry_permission=False,
            exit_submission_permission=False,reservation_release_permission=False,
            database_modified=False,production_ready=False),indent=2))
        raise SystemExit(1)
