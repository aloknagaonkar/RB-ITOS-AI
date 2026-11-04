import json
from pathlib import Path
from hashlib import sha256


def sha(raw):return sha256(raw).hexdigest()
def need(ok,reason):
    if not ok:raise ValueError(reason)


def stage(source,destination,here):
    original=json.loads((source/'RELEASE-MANIFEST.json').read_text());files=dict(original['files'])
    need(not destination.exists(),'NEW_CANDIDATE_REQUIRED');destination.mkdir(mode=0o700)
    for name,digest in files.items():
        rel=Path(name);need(not rel.is_absolute() and '..' not in rel.parts,'SAFE_RELEASE_PATH_REQUIRED')
        p=source/rel;need(p.is_file() and not any(q.is_symlink() for q in (p,*p.parents)),'REGULAR_SOURCE_REQUIRED')
        raw=p.read_bytes();need(sha(raw)==digest,'INSTALLED_RELEASE_CHANGED')
        target=destination/rel;target.parent.mkdir(parents=True,exist_ok=True,mode=0o700);target.write_bytes(raw)
    added=[]
    for name in ['authority_contract.py','factory_adapter.py','authority_files.py','worker_binding.py','FACTORY-REGISTRATION.json']:
        relative='runtime/'+name;need(relative not in files,'FACTORY_CANDIDATE_MODULE_ALREADY_PRESENT')
        target=destination/relative;target.write_bytes((here/name).read_bytes());files[relative]=sha(target.read_bytes());added.append(relative)
    name='backend/market_lab/hilega_worker_registration_v1.py';p=destination/name;text=p.read_text()
    anchor='        return worker_poll(bridge,journal,factory=None)'
    need(text.count(anchor)==1,'CLOSED_WORKER_REGISTRATION_ANCHOR_CHANGED')
    text=text.replace(anchor,'        from worker_binding import default_worker_poll\n        return default_worker_poll(bridge,journal)')
    compile(text,name,'exec');p.write_text(text);files[name]=sha(p.read_bytes());changed=[name,*added]
    dependency='backend/market_lab/hilega_preparation_runtime_v1/dependencies.json';p=destination/dependency;deps=json.loads(p.read_text())
    for name in changed:
        if name in deps:need(deps[name]==original['files'][name],'OLD_DEPENDENCY_PIN_CHANGED')
        deps[name]=files[name]
    p.write_text(json.dumps(deps,indent=2)+'\n');files[dependency]=sha(p.read_bytes())
    for name,digest in deps.items():need(sha((destination/name).read_bytes())==digest,'CANDIDATE_DEPENDENCY_MISMATCH')
    manifest=dict(original,files=files,authority_registration_candidate=True,production_execution_enabled=False)
    (destination/'RELEASE-MANIFEST.json').write_text(json.dumps(manifest,indent=2)+'\n')
    for p in destination.rglob('*'):
        if p.is_file():p.chmod(0o400)
    for p in sorted((p for p in destination.rglob('*') if p.is_dir()),key=lambda p:len(p.parts),reverse=True):p.chmod(0o500)
    destination.chmod(0o500)
    return dict(changed_modules=changed,changed_dependency_manifest=dependency,release_sha256=sha((destination/'RELEASE-MANIFEST.json').read_bytes()),
        factory_registration_enabled=False,execution_port_bytes_unchanged=files['backend/market_lab/hilega_execution_port_v1/adapter.py']==original['files']['backend/market_lab/hilega_execution_port_v1/adapter.py'])
