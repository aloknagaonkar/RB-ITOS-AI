"""Narrow compatibility update for the exact approved closed-hook source delta."""
import ast
from copy import deepcopy
import hashlib
import json
from pathlib import Path

SOURCE='backend/market_lab/hilega_preparation_runtime_v1/source.py'
GUARD='backend/market_lab/hilega_exclusive_closed_route_v1.py'
OLD_SOURCE='dbfce30057763b93e8f7f8332e86e2145890bd29c72d18016b3ad944125e6150'
NEW_SOURCE='d451edda4f7f28bfa38d2e095a543d4e36b83b9484027fb1ddff1375464b22e2'
NEW_GUARD='f8fd3bf253b4faf94517c7b520de75e72217e519aa8aa7fa47b95210f0f05844'
APPROVED='55ba58b26771b81ade1511e0b9f3324767fbc6768c2e2fa4d6ee3e6acbad4965'


def need(ok,reason):
    if not ok:raise ValueError(reason)


def sha(raw):return hashlib.sha256(raw).hexdigest()


def regular(path):
    p=Path(path);need(p.is_absolute() and p.is_file() and p.stat().st_size<=8_000_000
        and not any(q.is_symlink() for q in [p,*p.parents]),'REGULAR_BOUNDED_SOURCE_REQUIRED')
    return p.read_bytes()


def constant(text,name):
    found=[]
    for node in ast.parse(text).body:
        if isinstance(node,ast.Assign) and len(node.targets)==1 and isinstance(node.targets[0],ast.Name) and node.targets[0].id==name:
            need(isinstance(node.value,ast.Constant) and isinstance(node.value.value,str),'LITERAL_HASH_CONSTANT_REQUIRED')
            found.append(node.value)
    need(len(found)==1,'EXACT_HASH_CONSTANT_REQUIRED');return found[0]


def replace_constant(text,name,value):
    node=constant(text,name);old=ast.get_source_segment(text,node)
    need(text.count(old)==1,'UNIQUE_HASH_LITERAL_REQUIRED')
    changed=text.replace(old,repr(value),1);compile(changed,name,'exec')
    before=ast.parse(text);after=ast.parse(changed)
    for tree in (before,after):
        for item in tree.body:
            if isinstance(item,ast.Assign) and len(item.targets)==1 and isinstance(item.targets[0],ast.Name) and item.targets[0].id==name:
                item.value=ast.Constant(value='NORMALIZED_HASH')
    need(ast.dump(before)==ast.dump(after),'UNEXPECTED_CODE_CHANGE');return changed


def prepare(repo,package,service,old_source):
    repo=Path(repo);package=Path(package);service=Path(service)
    old=regular(old_source);new=regular(repo/SOURCE);guard=regular(repo/GUARD)
    need(sha(old)==OLD_SOURCE and sha(new)==NEW_SOURCE and sha(guard)==NEW_GUARD,'EXACT_APPROVED_RUNTIME_HASHES_REQUIRED')
    anchor='    def run_source_once(self,path):'
    text=old.decode();need(text.count(anchor)==1,'EXACT_SOURCE_GUARD_ANCHOR_REQUIRED')
    expected='from market_lab.hilega_exclusive_closed_route_v1 import exclusive_source_guard\n'+text.replace(anchor,'    @exclusive_source_guard\n'+anchor,1)
    need(new.decode()==expected,'SOURCE_DELTA_NOT_EXACTLY_REVIEWED_GUARD')
    cli_raw=regular(package/'cli.py');manifest_raw=regular(package/'manifest.json');service_raw=regular(service)
    cli=cli_raw.decode();companion=service_raw.decode()
    need(constant(cli,'EXPECTED_MANIFEST').value==sha(manifest_raw),'ORIGINAL_MANIFEST_PIN_CHANGED')
    need(constant(companion,'CLI_SHA').value==sha(cli_raw),'ORIGINAL_COMPANION_CLI_PIN_CHANGED')
    manifest=json.loads(manifest_raw)
    need(manifest['model']=='HILEGA_OPERATIONAL_LIFECYCLE_PACKAGE_V1'
        and manifest['order_actions_available'] is False and manifest['production_execution_enabled'] is False,
        'EXACT_READ_ONLY_PACKAGE_REQUIRED')
    need(manifest['runtime'].get(SOURCE)==OLD_SOURCE and GUARD not in manifest['runtime'],'EXACT_OLD_RUNTIME_CONTRACT_REQUIRED')
    for name,digest in manifest['modules'].items():
        p=Path(name);need(p.name==name and p.suffix=='.py','PACKAGE_PATH_INVALID')
        need(sha(regular(package/p))==digest,'UNRELATED_PACKAGE_MODULE_CHANGED')
    for name,digest in manifest['runtime'].items():
        p=Path(name);need(not p.is_absolute() and '..' not in p.parts and p.parts[0]=='backend' and p.suffix=='.py','RUNTIME_PATH_INVALID')
        if name!=SOURCE:need(sha(regular(repo/p))==digest,'UNRELATED_RUNTIME_MODULE_CHANGED')
    updated=deepcopy(manifest);updated['runtime'][SOURCE]=NEW_SOURCE;updated['runtime'][GUARD]=NEW_GUARD
    new_manifest=(json.dumps(updated,indent=2,sort_keys=True)+'\n').encode()
    new_cli=replace_constant(cli,'EXPECTED_MANIFEST',sha(new_manifest)).encode()
    new_service=replace_constant(companion,'CLI_SHA',sha(new_cli)).encode()
    return dict(originals={'manifest.json':manifest_raw,'cli.py':cli_raw,'service.py':service_raw},
        replacements={'manifest.json':new_manifest,'cli.py':new_cli,'service.py':new_service},manifest=updated)
