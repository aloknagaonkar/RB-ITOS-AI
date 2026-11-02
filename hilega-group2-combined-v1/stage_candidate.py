"""New immutable candidate only; preserve every original byte except the reviewed read-only guard insertion."""
import ast,hashlib,json
from pathlib import Path

def need(ok,reason):
    if not ok:raise ValueError(reason)
def sha(raw):return hashlib.sha256(raw).hexdigest()
def stage(original,destination,policy):
    need(not destination.exists(),'NEW_CANDIDATE_DESTINATION_REQUIRED');destination.mkdir(mode=0o700)
    raw=(original/'RELEASE-MANIFEST.json').read_bytes();manifest=json.loads(raw);files=dict(manifest['files'])
    for name,digest in files.items():
        rel=Path(name);need(not rel.is_absolute() and '..' not in rel.parts,'RELATIVE_CANDIDATE_PATH_REQUIRED')
        source=original/rel;need(source.is_file() and not any(p.is_symlink() for p in [source,*source.parents]),'REGULAR_CLOSED_SOURCE_REQUIRED')
        data=source.read_bytes();need(sha(data)==digest,'ORIGINAL_RELEASE_CHANGED')
        target=destination/rel;target.parent.mkdir(parents=True,exist_ok=True,mode=0o700);target.write_bytes(data)
    name='backend/market_lab/hilega_production_account_adapter_v1.py';target=destination/name;text=target.read_text();tree=ast.parse(text)
    functions=[n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='normalise'];need(len(functions)==1,'EXACT_ACCOUNT_NORMALIZER_REQUIRED');node=functions[0]
    need([n.arg for n in node.args.args]==['raw_orders','raw_trades','raw_positions'] and 'observed_at' in [n.arg for n in node.args.kwonlyargs],'REVIEWED_NORMALIZER_SIGNATURE_REQUIRED')
    first=node.body[0];line=text.splitlines(keepends=True)[first.lineno-1]
    need('observed=aware(observed_at)' in line,'REVIEWED_NORMALIZER_ENTRY_REQUIRED')
    addition="    from .hilega_broker_time_consistency_v1 import inspect_book\n    _timestamp_review=inspect_book(raw_orders,raw_trades,observed_at=observed_at)\n    if _timestamp_review['review_required']:\n        raise AdapterBlocked('BROKER_TIMESTAMP_SEMANTICS_UNVERIFIED')\n"
    lines=text.splitlines(keepends=True);lines.insert(first.end_lineno,addition);changed=''.join(lines);compile(changed,str(target),'exec');target.write_text(changed);files[name]=sha(target.read_bytes())
    new='backend/market_lab/hilega_broker_time_consistency_v1.py';need(new not in files,'TIMESTAMP_GUARD_ALREADY_PRESENT');(destination/new).write_bytes(policy);files[new]=sha(policy)
    new_manifest=dict(manifest,files=files,timestamp_semantics_review_guard_added=True,timestamps_automatically_shifted=False)
    (destination/'RELEASE-MANIFEST.json').write_text(json.dumps(new_manifest,indent=2)+'\n')
    for file in destination.rglob('*'):
        if file.is_file():file.chmod(0o400)
    for directory in sorted((x for x in destination.rglob('*') if x.is_dir()),key=lambda x:len(x.parts),reverse=True):directory.chmod(0o500)
    destination.chmod(0o500)
    return dict(original_release_sha256=sha(raw),candidate_release_sha256=sha((destination/'RELEASE-MANIFEST.json').read_bytes()),changed_modules=[name,new],installed_sources_modified=False)
