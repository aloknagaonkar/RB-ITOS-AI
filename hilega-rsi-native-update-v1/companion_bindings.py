"""Validate and reissue only explicitly staged source pins; retain closed authority."""
import hashlib
import json
from pathlib import Path
import subprocess
import sys

PACKAGE=Path("hilega-operational-lifecycle-tools-6cexrur_")
SERVICE=Path("hilega-reference-service-stage-yup3_wr1/lifecycle_reference_service.py")

def digest(raw):return hashlib.sha256(raw).hexdigest()


def regular(path):
    if path.is_symlink() or not path.is_file() or any(p.is_symlink() for p in path.absolute().parents):
        raise ValueError('COMPANION_REGULAR_SOURCE_REQUIRED:'+str(path.name))
    return path.read_bytes()


def current_service_args(repo):
    result=subprocess.run(['systemctl','--user','show','hilega-lifecycle-reference.service','-p','MainPID','--value'],
        capture_output=True,text=True,timeout=30,check=True)
    pid=result.stdout.strip()
    if not pid.isdigit() or pid=='0':raise ValueError('REFERENCE_COMPANION_NOT_RUNNING')
    arguments=Path('/proc',pid,'cmdline').read_bytes().decode().split('\0')
    cwd=Path('/proc',pid,'cwd').resolve()
    entry=None
    for index,value in enumerate(arguments):
        if value.endswith('.py'):
            path=Path(value);path=path if path.is_absolute() else cwd/path
            if path.resolve()==(repo/SERVICE).resolve():entry=index;break
    if entry is None:raise ValueError('REFERENCE_SERVICE_ENTRYPOINT_CHANGED')
    tail=[arg for arg in arguments[entry+1:] if arg]
    for option,expected in (('--repo',repo),('--package',repo/PACKAGE)):
        if tail.count(option)!=1:raise ValueError('REFERENCE_SERVICE_ARGUMENT_MISSING:'+option)
        pos=tail.index(option)+1;value=Path(tail[pos]);value=value if value.is_absolute() else cwd/value
        if value.resolve()!=expected.resolve():raise ValueError('REFERENCE_SERVICE_PATH_CHANGED:'+option)
    modes=[value for value in tail if value in ('--watch','--once','--check')]
    if modes!=['--watch']:raise ValueError('EXPECTED_WATCH_COMPANION')
    for option in ('--application','--adapter','--pin-file','--env-file','--journal'):
        if tail.count(option)!=1:raise ValueError('REFERENCE_SOURCE_ARGUMENT_MISSING:'+option)
        index=tail.index(option)+1;path=Path(tail[index])
        tail[index]=str(path if path.is_absolute() else cwd/path)
    return tail


def rebind(original,updates):
    raw=original[str(PACKAGE/'manifest.json')]
    manifest=json.loads(raw)
    if (manifest.get('model')!='HILEGA_OPERATIONAL_LIFECYCLE_PACKAGE_V1'
            or manifest.get('order_actions_available') is not False
            or manifest.get('production_execution_enabled') is not False):
        raise ValueError('COMPANION_CLOSED_AUTHORITY_REQUIRED')
    old_runtime=dict(manifest['runtime'])
    runtime=dict(old_runtime)
    for relative,data in updates.items():
        path=Path(relative)
        if path.is_absolute() or '..' in path.parts:
            raise ValueError('RUNTIME_UPDATE_PATH_INVALID')
        if not path.parts or path.parts[0]!='backend':continue
        if path.suffix!='.py':
            # Runtime companion pins cover Python modules only. This exact HTML
            # asset remains covered by the package and installation hash leases.
            if relative=='backend/market_lab/hilega_rsi_two_route_v1/workspace.html':
                continue
            raise ValueError('RUNTIME_UPDATE_PATH_INVALID')
        runtime[relative]=digest(data)
    manifest['runtime']=dict(sorted(runtime.items()))
    updated_manifest=(json.dumps(manifest,indent=2,sort_keys=True)+'\n').encode()
    cli=original[str(PACKAGE/'cli.py')].decode()
    old_manifest_anchor="EXPECTED_MANIFEST = '"+digest(raw)+"'"
    if cli.count(old_manifest_anchor)!=1:raise ValueError('COMPANION_MANIFEST_ANCHOR_CHANGED')
    new_cli=cli.replace(old_manifest_anchor,"EXPECTED_MANIFEST = '"+digest(updated_manifest)+"'").encode()
    service=original[str(SERVICE)].decode()
    old_cli_anchor="CLI_SHA = '"+digest(original[str(PACKAGE/'cli.py')])+"'"
    if service.count(old_cli_anchor)!=1:raise ValueError('SERVICE_CLI_ANCHOR_CHANGED')
    new_service=service.replace(old_cli_anchor,"CLI_SHA = '"+digest(new_cli)+"'").encode()
    return dict(files={str(PACKAGE/'manifest.json'):updated_manifest,str(PACKAGE/'cli.py'):new_cli,str(SERVICE):new_service},
        changed_runtime=sorted(n for n in old_runtime if old_runtime[n]!=runtime[n]),
        added_runtime=sorted(set(runtime)-set(old_runtime)),
        unchanged_runtime_count=sum(old_runtime[n]==runtime[n] for n in old_runtime),
        old_runtime_count=len(old_runtime),new_runtime_count=len(runtime))


def service_check_arguments(arguments,repo,package):
    args=list(arguments);args[args.index('--watch')]='--check'
    args[args.index('--repo')+1]=str(repo)
    args[args.index('--package')+1]=str(package)
    return args


def check_candidate(repo,package,service,arguments):
    run=subprocess.run([sys.executable,'-B',str(package/'cli.py'),'check','--repo',str(repo)],
        capture_output=True,text=True,timeout=60)
    if run.returncode:raise ValueError('CANDIDATE_COMPANION_RUNTIME_CHECK_FAILED')
    report=json.loads(run.stdout)
    if (report.get('status')!='PACKAGE_AND_RUNTIME_CHECK_PASS'
            or report.get('database_access_performed') is not False
            or report.get('credentials_opened') is not False
            or report.get('broker_reads_performed') is not False
            or report.get('order_actions_available') is not False
            or report.get('production_execution_enabled') is not False):
        raise ValueError('CANDIDATE_COMPANION_CHECK_FLAGS_INVALID')
    run=subprocess.run([sys.executable,'-B',str(service),*service_check_arguments(arguments,repo,package)],
        capture_output=True,text=True,timeout=60)
    if run.returncode:raise ValueError('CANDIDATE_REFERENCE_SERVICE_STARTUP_CHECK_FAILED')
    service_report=json.loads(run.stdout)
    if (service_report.get('status')!='SERVICE_STARTUP_CHECK_PASS'
            or service_report.get('database_opened') is not False
            or service_report.get('token_loaded') is not False
            or service_report.get('production_execution_enabled') is not False):
        raise ValueError('REFERENCE_SERVICE_CHECK_FLAGS_INVALID')
    return dict(package_check=report,service_check=service_report)

