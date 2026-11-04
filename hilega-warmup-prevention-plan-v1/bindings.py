import ast,hashlib,json
from copy import deepcopy

def need(ok,code):
    if not ok:raise ValueError(code)
def sha(raw):return hashlib.sha256(raw).hexdigest()

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



def chain(manifest_raw,cli_raw,service_raw,source_name,old_sha,new_sha):
    manifest=json.loads(manifest_raw);cli=cli_raw.decode();service=service_raw.decode()
    need(manifest['model']=='HILEGA_OPERATIONAL_LIFECYCLE_PACKAGE_V1' and manifest['production_execution_enabled'] is False and manifest['order_actions_available'] is False,'CLOSED_REFERENCE_PACKAGE_REQUIRED')
    need(constant(cli,'EXPECTED_MANIFEST').value==sha(manifest_raw),'ORIGINAL_CLI_MANIFEST_BINDING_CHANGED')
    need(constant(service,'CLI_SHA').value==sha(cli_raw),'ORIGINAL_SERVICE_CLI_BINDING_CHANGED')
    need(manifest['runtime'].get(source_name)==old_sha,'ORIGINAL_WRITER_BINDING_CHANGED')
    updated=deepcopy(manifest);updated['runtime'][source_name]=new_sha
    new_manifest=(json.dumps(updated,indent=2,sort_keys=True)+'\n').encode()
    new_cli=replace_constant(cli,'EXPECTED_MANIFEST',sha(new_manifest)).encode()
    new_service=replace_constant(service,'CLI_SHA',sha(new_cli)).encode()
    need({k:v for k,v in updated['runtime'].items() if k!=source_name}=={k:v for k,v in manifest['runtime'].items() if k!=source_name},'UNRELATED_RUNTIME_PIN_CHANGED')
    return new_manifest,new_cli,new_service
