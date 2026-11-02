"""Immutable candidate bundle assembly; all mutations confined to a new review folder."""
import hashlib
import json
from pathlib import Path
import shutil


def sha(raw):return hashlib.sha256(raw).hexdigest()


def need(ok,reason):
    if not ok:raise ValueError(reason)


def regular(path):
    p=Path(path);need(p.is_absolute() and p.is_file() and not any(q.is_symlink() for q in [p,*p.parents]),'REGULAR_RELEASE_INPUT_REQUIRED')
    return p.read_bytes()


def place(root,relative,raw,files):
    rel=Path(relative);need(not rel.is_absolute() and '..' not in rel.parts and bool(rel.parts),'RELATIVE_RELEASE_PATH_REQUIRED')
    name=rel.as_posix();digest=sha(raw)
    if name in files:need(files[name]==digest,'RELEASE_PATH_COLLISION');return
    target=root/rel;target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(raw);files[name]=digest


def assemble(repo,stage,graph,dynamic_pins,wheel,lock,destination):
    need(not destination.exists(),'NEW_RELEASE_DIRECTORY_REQUIRED');destination.mkdir(mode=0o700)
    files={};aliases={'rules','analysis','preflight_contract_rules','preflight_cash_gate',
        'preflight_market_collector','preflight_cash_analysis','preflight_cash_collector'}
    for name,row in graph['modules'].items():
        if name in aliases:continue
        path=Path(row['path']);raw=regular(path);need(sha(raw)==row['sha256'],'RELEASE_INPUT_CHANGED')
        if name.startswith('market_lab'):
            rel=Path('backend',*name.split('.'))
            rel=rel/'__init__.py' if path.name=='__init__.py' else rel.with_suffix('.py')
        else:
            need('.' not in name,'UNREVIEWED_MODULE_LAYOUT');rel=Path('runtime',name+'.py')
        place(destination,rel,raw,files)
    for relative,digest in dynamic_pins.items():
        raw=regular(repo/relative);need(sha(raw)==digest,'DYNAMIC_INPUT_CHANGED');place(destination,relative,raw,files)
    worker=regular(stage/'scripts/hilega_production_simulator_bridge.py')
    need(b'result=worker_poll(bridge,a.source)' in worker,'CLOSED_FACTORY_CALLSITE_REQUIRED')
    place(destination,'scripts/hilega_production_simulator_bridge.py',worker,files)
    raw=regular(wheel);need(sha(raw)==lock['wheel_sha256'],'LOCKED_WHEEL_CHANGED')
    place(destination,'wheels/'+wheel.name,raw,files)
    place(destination,'requirements-candidate.lock',('--only-binary=:all:\n'+lock['requirement']+'\n').encode(),files)
    for relative in files:
        if relative.endswith('.py'):compile((destination/relative).read_bytes(),relative,'exec')
    manifest=dict(model='HILEGA_CLOSED_CANDIDATE_RELEASE_ASSEMBLY_V1',files=files,
        candidate_import_graph_bundled=True,full_application_service_closure_verified=False,
        runtime_registration_installed=False,production_execution_enabled=False)
    (destination/'RELEASE-MANIFEST.json').write_text(json.dumps(manifest,indent=2)+'\n')
    return manifest


def verify(root,manifest):
    for name,digest in manifest['files'].items():
        rel=Path(name);need(not rel.is_absolute() and '..' not in rel.parts,'RELATIVE_RELEASE_PATH_REQUIRED')
        need(sha(regular(root/rel))==digest,'RELEASE_FILE_CHANGED: '+name)
    actual={p.relative_to(root).as_posix() for p in root.rglob('*') if p.is_file()}
    need(actual==set(manifest['files'])|{'RELEASE-MANIFEST.json'},'UNMANIFESTED_RELEASE_FILE')
    return True


def disposable_rollback(review):
    root=review/'rollback-rehearsal';root.mkdir();target=root/'worker.py';backup=root/'worker.py.backup'
    original=b'# disposable original\n';candidate=b'# disposable candidate\n'
    target.write_bytes(original);backup.write_bytes(original);target.write_bytes(candidate)
    need(sha(target.read_bytes())==sha(candidate),'DISPOSABLE_APPLY_FAILED')
    shutil.copyfile(backup,target);need(target.read_bytes()==original,'DISPOSABLE_ROLLBACK_FAILED')
    return dict(status='DISPOSABLE_FILE_ROLLBACK_PASS',actual_runtime_rollback_tested=False,live_databases_restored=False)
