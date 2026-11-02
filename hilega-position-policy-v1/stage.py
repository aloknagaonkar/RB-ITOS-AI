import json
from pathlib import Path
from hashlib import sha256


def need(ok, reason):
    if not ok: raise ValueError(reason)


def sha(raw):return sha256(raw).hexdigest()


def stage(source, destination, here):
    raw=(source/'RELEASE-MANIFEST.json').read_bytes();manifest=json.loads(raw);files=dict(manifest['files'])
    need(not destination.exists(),'NEW_POLICY_CANDIDATE_REQUIRED');destination.mkdir(mode=0o700)
    for name,digest in files.items():
        rel=Path(name);need(not rel.is_absolute() and '..' not in rel.parts,'SAFE_RELEASE_PATH_REQUIRED')
        p=source/rel;need(not any(q.is_symlink() for q in (p,*p.parents)) and p.is_file(),'REGULAR_SOURCE_REQUIRED')
        data=p.read_bytes();need(sha(data)==digest,'SOURCE_RELEASE_CHANGED')
        target=destination/rel;target.parent.mkdir(parents=True,exist_ok=True,mode=0o700);target.write_bytes(data)
    changed=[]
    for name in ['runtime/existing_request_attempt_v1.py','runtime/history_aware_attempt_v1.py']:
        need(name in files,'EXPECTED_ENTRY_ATTEMPT_MODULE_REQUIRED')
        target=destination/name;text=target.read_text()
        anchor="            wire=adapter._wire(request,'PLACE');aid=uuid.uuid4().hex\n"
        need(text.count(anchor)==1 and 'hilega_position_policy_v1' not in text,'REVIEWED_ENTRY_ADMISSION_ANCHOR_CHANGED')
        addition="            from hilega_position_policy_v1 import enforce as _enforce_position_policy\n            _enforce_position_policy(db,pin,request_id)\n"
        text=text.replace(anchor,addition+anchor);compile(text,name,'exec');target.write_text(text)
        files[name]=sha(target.read_bytes());changed.append(name)
    for name in ['hilega_position_policy_v1.py','POSITION-POLICY.json']:
        target=destination/'runtime'/name;need('runtime/'+name not in files,'POSITION_POLICY_ALREADY_PRESENT')
        target.write_bytes((here/name).read_bytes());files['runtime/'+name]=sha(target.read_bytes());changed.append('runtime/'+name)
    dependency='backend/market_lab/hilega_preparation_runtime_v1/dependencies.json'
    p=destination/dependency;dependencies=json.loads(p.read_text())
    for name in changed:
        if name in dependencies:need(dependencies[name]==manifest['files'][name],'OLD_DEPENDENCY_PIN_CHANGED')
        dependencies[name]=files[name]
    p.write_text(json.dumps(dependencies,indent=2)+'\n');files[dependency]=sha(p.read_bytes())
    for name,digest in dependencies.items():need(sha((destination/name).read_bytes())==digest,'POLICY_DEPENDENCY_CHAIN_MISMATCH')
    manifest=dict(manifest,files=files,position_policy_candidate=True,production_execution_enabled=False)
    (destination/'RELEASE-MANIFEST.json').write_text(json.dumps(manifest,indent=2)+'\n')
    for p in destination.rglob('*'):
        if p.is_file():p.chmod(0o400)
    for p in sorted((p for p in destination.rglob('*') if p.is_dir()),key=lambda p:len(p.parts),reverse=True):p.chmod(0o500)
    destination.chmod(0o500)
    return dict(changed_modules=changed,changed_dependency_manifest=dependency,release_sha256=sha((destination/'RELEASE-MANIFEST.json').read_bytes()),
        execution_port_bytes_unchanged=files['backend/market_lab/hilega_execution_port_v1/adapter.py']==json.loads(raw)['files']['backend/market_lab/hilega_execution_port_v1/adapter.py'])
