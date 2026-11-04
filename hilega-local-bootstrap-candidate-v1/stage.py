import ast
import json
from pathlib import Path
from hashlib import sha256


def sha(raw):return sha256(raw).hexdigest()
def need(ok,reason):
    if not ok:raise ValueError(reason)


def stage(source,destination,here):
    original=json.loads((source/'RELEASE-MANIFEST.json').read_text());files=dict(original['files'])
    need(not destination.exists(),'NEW_BOOTSTRAP_CANDIDATE_REQUIRED');destination.mkdir(mode=0o700)
    for name,digest in files.items():
        rel=Path(name);need(not rel.is_absolute() and '..' not in rel.parts,'SAFE_RELEASE_PATH_REQUIRED')
        p=source/rel;need(p.is_file() and not any(q.is_symlink() for q in (p,*p.parents)),'REGULAR_SOURCE_REQUIRED')
        raw=p.read_bytes();need(sha(raw)==digest,'INSTALLED_SOURCE_CHANGED')
        target=destination/rel;target.parent.mkdir(parents=True,exist_ok=True,mode=0o700);target.write_bytes(raw)
    name='backend/market_lab/hilega_provisioning_workflow_v1.py';p=destination/name;old=p.read_text();tree=ast.parse(old)
    nodes=[n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='provision_and_enroll_candidate']
    need(len(nodes)==1 and 'provision_disabled_owner' not in old,'EXACT_EXISTING_PROVISIONER_REQUIRED')
    original_function=ast.get_source_segment(old,nodes[0]);changed=original_function
    replacements=[
        ('def provision_and_enroll_candidate(', 'def provision_disabled_owner('),
        ('*,clock,checkpoint=', '*,local_approval,clock,checkpoint='),
        ('    port.require_live_clearance() # No seed reads, file creation, keys or tokens behind the real closed gate.',
         "    from local_admission import LocalApproval\n    need(type(local_approval) is LocalApproval and local_approval.operation=='ENROLL_DISABLED_OWNER','EXACT_LOCAL_ENROLLMENT_APPROVAL_REQUIRED')\n    local_approval.check(source,store,pin,journal,seed,clock,private_parent)\n    upstream_checkpoint=checkpoint\n    def checkpoint(point):\n        local_approval.check_time(clock())\n        upstream_checkpoint(point)\n        local_approval.check_time(clock())"),
        ("    with route_lock(source.s.store.path):", "    need(not any(parent.glob('candidate-context-*')),'EXISTING_LOCAL_CONTEXT_REQUIRES_RECOVERY')\n    with route_lock(source.s.store.path):"),
        ("        token=secret_provider();", "        local_approval.check_time(clock())\n        token=secret_provider();"),
        ("        key=secrets.token_hex(32)","        local_approval.check_token_separation(token,clock)\n        key=secrets.token_hex(32)"),
        ("        while key==pin['key']:key=secrets.token_hex(32)","        while not local_approval.independent_authority_key(key,pin,clock):key=secrets.token_hex(32)"),
        ("        folder=Path(tempfile.mkdtemp(prefix='candidate-context-',dir=parent));", "        local_approval.check_time(clock())\n        folder=Path(tempfile.mkdtemp(prefix='candidate-context-',dir=parent));"),
        ("        fd=os.open(folder,os.O_DIRECTORY)","        _write(folder/'LOCAL-APPROVAL.json',local_approval.audit_record(clock))\n        fd=os.open(folder,os.O_DIRECTORY)"),
        ("            context=PrivateContextLoader(source,store,journal,folder/'context.json',digest,clock=clock)()", "            from local_context import validate_created_context\n            context=validate_created_context(session,folder/'context.json',digest,local_approval,clock)")]
    for before,after in replacements:
        need(changed.count(before)==1,'LOCAL_BOOTSTRAP_SOURCE_ANCHOR_CHANGED');changed=changed.replace(before,after)
    text=old+'\n\n'+changed+'\n';compile(text,name,'exec');p.write_text(text);files[name]=sha(p.read_bytes())
    after=ast.parse(text);old_after=next(n for n in after.body if isinstance(n,ast.FunctionDef) and n.name=='provision_and_enroll_candidate')
    need(ast.dump(nodes[0],include_attributes=False)==ast.dump(old_after,include_attributes=False),'ORIGINAL_CLOSED_ENTRYPOINT_CHANGED')
    additions=[]
    for filename in ['local_admission.py','local_context.py']:
        relative='runtime/'+filename;need(relative not in files,'LOCAL_BOOTSTRAP_ALREADY_PRESENT')
        target=destination/relative;target.write_bytes((here/filename).read_bytes());files[relative]=sha(target.read_bytes());additions.append(relative)
    dependency='backend/market_lab/hilega_preparation_runtime_v1/dependencies.json';p=destination/dependency;deps=json.loads(p.read_text())
    for relative in [name,*additions]:
        if relative in deps:need(deps[relative]==original['files'][relative],'OLD_DEPENDENCY_CHANGED')
        deps[relative]=files[relative]
    p.write_text(json.dumps(deps,indent=2)+'\n');files[dependency]=sha(p.read_bytes())
    for relative,digest in deps.items():need(sha((destination/relative).read_bytes())==digest,'LOCAL_BOOTSTRAP_DEPENDENCY_CHANGED')
    manifest=dict(original,files=files,local_disabled_enrollment_candidate=True)
    (destination/'RELEASE-MANIFEST.json').write_text(json.dumps(manifest,indent=2)+'\n')
    for p in destination.rglob('*'):
        if p.is_file():p.chmod(0o400)
    for p in sorted((p for p in destination.rglob('*') if p.is_dir()),key=lambda p:len(p.parts),reverse=True):p.chmod(0o500)
    destination.chmod(0o500)
    return dict(release_sha256=sha((destination/'RELEASE-MANIFEST.json').read_bytes()),changed_modules=[name,*additions],
        changed_dependency_manifest=dependency,original_closed_entrypoint_ast_unchanged=True,
        execution_port_bytes_unchanged=files['backend/market_lab/hilega_execution_port_v1/adapter.py']==original['files']['backend/market_lab/hilega_execution_port_v1/adapter.py'])
