"""Static runtime closure assembly. Never imports candidate or broker modules."""
import ast
import hashlib
from pathlib import Path
import sys


def build(stage,roots,*,seeds=None,file_map=None):
    stage=Path(stage);queue=['closed_application_coordinator_v1','market_lab.hilega_runtime_bootstrap_v1',
        'market_lab.hilega_private_context_v1','market_lab.hilega_provisioning_workflow_v1']
    if seeds is not None:queue=list(seeds)
    file_map=file_map or {}
    seen=set();modules={};external=set();unresolved=set();dynamic=[]
    def find(name):
        if name in file_map:return Path(file_map[name])
        relative=Path(*name.split('.'))
        for root in roots:
            for tail in (relative.with_suffix('.py'),relative/'__init__.py'):
                p=Path(root)/tail
                if p.is_file():return p
        return None
    while queue:
        name=queue.pop()
        if name in seen:continue
        seen.add(name)
        if name.split('.')[0] in sys.stdlib_module_names:continue
        p=find(name)
        if p is None:
            (unresolved if name.startswith('market_lab.') or name.endswith('_v1') or name.endswith('_candidate') else external).add(name)
            continue
        if p.is_symlink() or any(q.is_symlink() for q in p.absolute().parents):raise ValueError('REGULAR_RUNTIME_REQUIRED')
        raw=p.read_bytes();tree=ast.parse(raw);package=name if p.name=='__init__.py' else name.rpartition('.')[0]
        modules[name]={'path':str(p),'sha256':hashlib.sha256(raw).hexdigest()}
        # Flat candidate modules are consolidated into the stage, preserving their import names.
        if '.' not in name and name not in file_map:
            target=stage/(name+'.py')
            if target.exists() and target.read_bytes()!=raw:raise ValueError('RUNTIME_MODULE_COLLISION: '+name)
            target.write_bytes(raw)
        for node in ast.walk(tree):
            if isinstance(node,ast.Import):queue.extend(a.name for a in node.names)
            elif isinstance(node,ast.ImportFrom):
                base=node.module or ''
                if node.level:
                    parts=package.split('.') if package else []
                    base='.'.join(parts[:len(parts)-node.level+1]+([base] if base else []))
                if base:queue.append(base)
                for alias in node.names:
                    child=(base+'.' if base else '')+alias.name
                    if find(child):queue.append(child)
            elif isinstance(node,ast.Call):
                label=ast.unparse(node.func)
                if label in {'__import__','importlib.import_module','importlib.util.spec_from_file_location','runpy.run_path'}:
                    dynamic.append({'module':name,'line':node.lineno,'call':label})
    return dict(modules=modules,unresolved_local=sorted(unresolved),external_imports=sorted(external),
        dynamic_loading_sites=dynamic,external_distributions_locked=False,dynamic_loading_review_complete=False,
        dependency_manifest_fully_reconciled=False)
