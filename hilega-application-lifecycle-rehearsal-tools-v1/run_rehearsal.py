"""Validate installed source, then run only isolated synthetic rehearsal tests."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys


def digest(path):
    if path.is_symlink() or not path.is_file():
        raise ValueError('REGULAR_SOURCE_FILE_REQUIRED:' + path.name)
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo',type=Path,default=Path.cwd())
    args=parser.parse_args()
    repo=args.repo.resolve();folder=Path(__file__).resolve().parent
    manifest=json.loads((folder/'manifest.json').read_text())
    for relative,expected in manifest['package_sha256'].items():
        if digest(folder/relative)!=expected:
            raise ValueError('PACKAGE_HASH_MISMATCH:' + relative)
    for relative,expected in manifest['installed_source_sha256'].items():
        if digest(repo/relative)!=expected:
            raise ValueError('INSTALLED_SOURCE_HASH_MISMATCH:' + relative)
    for relative in ('tests/test_hilega_application_preparation_v1.py',
                     'tests/test_hilega_atomic_disabled_binding_v1.py',
                     'tests/hilega_application_preparation_fixtures.py'):
        digest(repo/relative)
    environment=os.environ.copy()
    environment['PYTHONPATH']=os.pathsep.join(map(str,(
        folder,repo/'backend',repo/'tests',repo)))
    result=subprocess.run([sys.executable,'-m','pytest','-q',str(folder)],
                          cwd=repo,env=environment,check=False)
    now=datetime.now(timezone.utc)
    report=dict(model='HILEGA_APPLICATION_LIFECYCLE_REHEARSAL_V1',
        status='PASS' if result.returncode==0 else 'FAILED_REVIEW_REQUIRED',
        assessed_at=now.isoformat(),pytest_exit_code=result.returncode,
        scope='SYNTHETIC_TEMPORARY_DATABASES_ONLY',
        deployed_entry_code_exercised=result.returncode==0,
        separate_fixture_execution_handoff=True,
        entry_allocation_fraction='0.50',daily_loss_limit_required=False,
        application_code_applied=False,running_services_changed=False,
        production_exit_dispatch_integrated=False,
        runtime_live_lifecycle_integrated=False,
        live_evidence_assessed=False,orders_sent_to_upstox=False,
        production_execution_enabled=False,reservation_release_permission=False,
        production_ready=False)
    output=folder/('APPLICATION_LIFECYCLE_REHEARSAL-'+now.strftime('%Y%m%dT%H%M%SZ')+'.json')
    report['report']=str(output)
    output.write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(report,indent=2))
    return result.returncode


if __name__=='__main__':
    try:
        raise SystemExit(main())
    except ValueError as exc:
        print(json.dumps({'status':'STOPPED_FOR_REVIEW','reason':str(exc),
                          'production_execution_enabled':False}))
        raise SystemExit(1)
