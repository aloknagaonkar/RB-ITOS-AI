"""Read-only readiness evidence. Never authorizes execution or changes services."""
import ast
from contextlib import closing
import hashlib
import hmac
from importlib.machinery import PathFinder
import importlib.util
import json
from pathlib import Path
import sqlite3
import sys
from datetime import datetime
from zoneinfo import ZoneInfo

SUPERVISOR_SHA='cd7286892f5099ab962d3a179aff15642cce20ccd59727e21c83ab3b6e707e8a'
APP_TABLES=('preparation_plans','preparation_shadow_holds','preparation_outbox','preparation_request_bindings',
 'preparation_cash_reservations','preparation_candidate_closed_cycle_archives_v1',
 'preparation_candidate_reference_retirements_v1','preparation_execution_adoption_candidates_v1')
OWNER='preparation_candidate_exclusive_source_owner_v1'
COORDINATOR='preparation_candidate_coordinator_state_v1'
PHASES={'BUY_PENDING','ENTRY_REVIEW','ENTRY_UNKNOWN','WAIT_EXIT','SELL_PENDING','EXIT_REVIEW',
 'EXIT_UNKNOWN','CLOSEOUT_PENDING','RETIRE_PENDING','WAIT_NEXT','PREPARE_PENDING'}


def need(ok,reason):
    if not ok:raise ValueError(reason)


def sha(raw):return hashlib.sha256(raw).hexdigest()


def regular(path,limit=4_000_000):
    p=Path(path)
    need(p.is_absolute(),'ABSOLUTE_PATH_REQUIRED')
    need(not any(q.is_symlink() for q in [p,*p.parents]),'SYMLINK_PATH_FORBIDDEN')
    need(p.is_file() and p.stat().st_size<=limit,'BOUNDED_REGULAR_FILE_REQUIRED')
    return p.read_bytes()


def approval_bindings(text):
    """Extract known supervisor permit digest comparisons without executing source."""
    found={}
    for node in ast.walk(ast.parse(text)):
        if not isinstance(node,ast.Compare) or len(node.ops)!=1 or not isinstance(node.ops[0],ast.Eq):continue
        left=node.left;right=node.comparators[0]
        if not (isinstance(left,ast.Call) and isinstance(left.func,ast.Attribute) and isinstance(left.func.value,ast.Name)
            and left.func.value.id=='permit' and left.func.attr=='get' and len(left.args)==1
            and isinstance(left.args[0],ast.Constant) and isinstance(left.args[0].value,str)):continue
        if not (isinstance(right,ast.Call) and isinstance(right.func,ast.Name) and right.func.id=='digest' and len(right.args)==1):continue
        expr=right.args[0]
        if isinstance(expr,ast.BinOp) and isinstance(expr.right,ast.Constant) and expr.right.value=='config-private.json':
            found[left.args[0].value]='config'
        elif isinstance(expr,ast.Call) and isinstance(expr.func,ast.Name) and expr.func.id=='Path' and len(expr.args)==1 and isinstance(expr.args[0],ast.Name) and expr.args[0].id=='__file__':
            found[left.args[0].value]='runner'
    need(set(found.values())=={'config','runner'} and len(found)==2,'SUPERVISOR_APPROVAL_CONTRACT_NOT_RECOGNIZED')
    return found


def supervisor_review(repo,home):
    repo=Path(repo).resolve();folder=Path(home)/'hilega-persistent-supervision-stage-v1'
    report=dict(status='BLOCKED',approval_hashes_match=False,private_values_exported=False,
        environment_file_opened=False,approvals_modified=False,services_changed=False)
    context={}
    try:
        raw=regular(folder/'runner.py');need(sha(raw)==SUPERVISOR_SHA,'SUPERVISOR_CHANGED')
        config_raw=regular(folder/'config-private.json');permit=json.loads(regular(folder/'MIGRATION_APPROVED.json'))
        bindings=approval_bindings(raw.decode());digests=dict(config=sha(config_raw),runner=sha(raw))
        matched=all(isinstance(permit.get(k),str) and hmac.compare_digest(permit[k],digests[v]) for k,v in bindings.items())
        need(matched,'SUPERVISOR_APPROVAL_HASH_MISMATCH')
        config=json.loads(config_raw);need(config['root']==str(repo),'SUPERVISOR_ROOT_CHANGED')
        item=config['startup']['production-source-worker'];argv=item['argv'];environment=item['env']
        expected=str(repo/'scripts/hilega_production_simulator_bridge.py')
        need(isinstance(argv,list) and argv[:3]==[str(repo/'.venv/bin/python'),'-u',expected]
             and '--watch' in argv and not any(a in argv for a in ('--demo','--synthetic-fills','--synthetic-cash')),
             'SUPERVISOR_SOURCE_COMMAND_CHANGED')
        need(environment.get('HILEGA_PRODUCTION_EXECUTION_ROUTE')=='PREPARATION_ONLY'
             and environment.get('HILEGA_PRODUCTION_WORKSPACE_MODE')=='SIMULATION_ONLY','SUPERVISOR_CLOSED_ROUTE_REQUIRED')
        context={k:environment[k] for k in ('HILEGA_PRODUCTION_SIM_DB','HILEGA_PREPARATION_ADAPTER_DB') if isinstance(environment.get(k),str)}
        report.update(status='REVIEWED_APPROVAL_BINDINGS_MATCH',approval_hashes_match=True,
            source_command_matches=True,captured_environment_closed_route=True,
            environment_hash_revalidated=False,complete_release_approval_reconciled=False)
    except (OSError,ValueError,KeyError,TypeError,SyntaxError,UnicodeError):
        report['reason']='SUPERVISOR_CONTRACT_OR_APPROVAL_REQUIRES_REVIEW'
    return report,context


def database_snapshot(path,kind):
    """One query-only SQLite snapshot; exports counts and restricted state labels only."""
    path=Path(path);result=dict(kind=kind,status='BLOCKED',database_opened=False,sql_mutations_issued=False,
        signed_ownership_verified=False,broker_reconciliation_verified=False)
    try:
        need(path.is_absolute() and path.is_file() and not any(p.is_symlink() for p in [path,*path.parents]),'REGULAR_DATABASE_REQUIRED')
        with closing(sqlite3.connect(path.as_uri()+'?mode=ro',uri=True,timeout=3)) as db:
            result['database_opened']=True
            db.execute('PRAGMA query_only=ON');db.execute('BEGIN')
            tables={r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            result['journal_mode']=db.execute('PRAGMA journal_mode').fetchone()[0]
            result['schema_fingerprint']=sha(json.dumps(list(db.execute("SELECT name,sql FROM sqlite_master WHERE type='table' ORDER BY name"))).encode())
            wanted=APP_TABLES+(OWNER,COORDINATOR) if kind=='application' else ('requests','attempts','receipts','candidate_existing_request_claims_v1')
            result['counts']={t:db.execute('SELECT COUNT(*) FROM '+t).fetchone()[0] for t in wanted if t in tables}
            if kind=='application':
                need({'control','preparation_source','sim_stop_state'}<=tables,'APPLICATION_SCHEMA_INCOMPLETE')
                raw=db.execute('SELECT data FROM control WHERE id=1').fetchone();need(raw is not None,'CONTROL_REQUIRED');c=json.loads(raw[0])
                result['control_mode']=c['mode'] if c['mode'] in {'ARMED','PAUSED'} else 'OTHER'
                result['control_version']=c['version'] if type(c['version']) is int else None
                result['session_is_current_ist']=c.get('session_date')==datetime.now(ZoneInfo('Asia/Kolkata')).date().isoformat()
                stop=db.execute('SELECT generation,handled FROM sim_stop_state WHERE id=1').fetchone()
                result['stop_pending']=stop is None or stop[0]!=stop[1]
                source=db.execute('SELECT data FROM preparation_source WHERE id=1').fetchone()
                result['source_cursor_present']=source is not None
                if source:
                    cursor=json.loads(source[0]);result['source_sequence']=cursor.get('sequence') if type(cursor.get('sequence')) is int else None
                result['owner_migration_review_required']=OWNER in tables or COORDINATOR in tables
                if COORDINATOR in tables:
                    row=db.execute('SELECT data FROM '+COORDINATOR+' WHERE id=1').fetchone()
                    if row:
                        state=json.loads(row[0]);result['coordinator_phase']=state.get('phase') if state.get('phase') in PHASES else 'INVALID'
            else:
                need({'meta','requests','attempts','receipts'}<=tables,'ADAPTER_SCHEMA_INCOMPLETE')
                row=db.execute('SELECT data FROM meta WHERE id=1').fetchone();need(row is not None,'ADAPTER_META_REQUIRED')
                meta=json.loads(row[0]);result['adapter_is_live_closed']=meta.get('mode')=='LIVE_CLOSED'
                result['account_scope_fingerprint']=sha(json.dumps(meta.get('scope')).encode())
            db.rollback()
        result['status']='READ_ONLY_LOCAL_SNAPSHOT_OBSERVED'
        result['independent_database_snapshots_not_cross_database_atomic']=True
    except (OSError,ValueError,KeyError,TypeError,sqlite3.Error):result['reason']='DATABASE_SCHEMA_OR_READ_ONLY_ACCESS_REQUIRES_REVIEW'
    return result


def baseline(repo,context,*,application_db=None,adapter_db=None):
    repo=Path(repo).resolve();paths=[]
    for kind,explicit,key,default in (
        ('application',application_db,'HILEGA_PRODUCTION_SIM_DB','data/research/hilega-production-workspace/sim.sqlite'),
        ('adapter',adapter_db,'HILEGA_PREPARATION_ADAPTER_DB','data/research/hilega-broker-adapter-closed/adapter.sqlite')):
        chosen=explicit or context.get(key) or default
        source='EXPLICIT_ARGUMENT' if explicit else 'SUPERVISOR_CAPTURED_ENVIRONMENT' if key in context else 'DEFAULT_NOT_EFFECTIVE_ENV_VERIFIED'
        p=Path(chosen);p=p if p.is_absolute() else repo/p
        paths.append((kind,p,source))
    if paths[0][1].resolve()==paths[1][1].resolve():
        return dict(status='BLOCKED',reason='DISTINCT_DATABASES_REQUIRED',snapshots=[],live_database_inspected=False)
    snapshots=[]
    for kind,p,source in paths:
        row=database_snapshot(p,kind);row['path_selection']=source;snapshots.append(row)
    blockers=[]
    for row in snapshots:
        if row['status']!='READ_ONLY_LOCAL_SNAPSHOT_OBSERVED':blockers.append(row['kind'].upper()+'_BASELINE_UNAVAILABLE')
        if row['path_selection']=='DEFAULT_NOT_EFFECTIVE_ENV_VERIFIED':blockers.append(row['kind'].upper()+'_EFFECTIVE_PATH_NOT_CONFIRMED')
        if row.get('owner_migration_review_required'):blockers.append('EXISTING_OWNER_OR_COORDINATOR_REQUIRES_AUTHENTICATED_MIGRATION_REVIEW')
        if row.get('control_mode')=='ARMED' or row.get('stop_pending'):blockers.append('CONTROLLER_NOT_QUIESCENT')
        if row.get('counts',{}).get('preparation_plans',0):blockers.append('EXISTING_PREPARATION_REQUIRES_ADOPTION_REVIEW')
        if row.get('kind')=='adapter' and row.get('adapter_is_live_closed') is False:blockers.append('ADAPTER_MODE_REQUIRES_REVIEW')
    return dict(status='READ_ONLY_BASELINE_CAPTURED' if all(r['status']=='READ_ONLY_LOCAL_SNAPSHOT_OBSERVED' for r in snapshots) else 'BASELINE_INCOMPLETE',
        snapshots=snapshots,blockers=sorted(set(blockers)),live_database_inspected=any(r['database_opened'] for r in snapshots),
        migration_approved=False,production_ready=False)


def resolve_static(name,search_paths,staged):
    if name in staged:return dict(origin=staged[name],package=False)
    paths=list(map(str,search_paths));spec=None
    for i in range(len(name.split('.'))):
        try:
            spec=PathFinder.find_spec('.'.join(name.split('.')[:i+1]),paths)
            if spec is None:return None
            locations=spec.submodule_search_locations
            paths=list(getattr(locations,'_path',locations) or [])
        except (ImportError,KeyError,ValueError):return None
    return dict(origin=Path(spec.origin) if spec.origin and spec.origin not in {'built-in','frozen'} else None,
        package=spec.submodule_search_locations is not None)


def transitive_inventory(entries,search_paths,local_roots,staged,*,max_modules=250,flat_roots=()):
    """Bounded local Python import graph, including optional/conditional imports. No execution."""
    queue=list(entries);seen={};missing=set();blockers=[]
    roots=[Path(p).resolve() for p in local_roots]
    while queue:
        name=queue.pop(0)
        if name in seen or name in missing:continue
        if len(seen)>=max_modules:blockers.append('LOCAL_MODULE_SCAN_LIMIT_REACHED');break
        if name.split('.')[0] in sys.stdlib_module_names:
            seen[name]=dict(module=name,kind='STANDARD_LIBRARY');continue
        spec=resolve_static(name,search_paths,staged)
        if spec is None:missing.add(name);continue
        path=spec['origin'];row=dict(module=name,kind='EXTERNAL_OR_NAMESPACE')
        local=path is not None and (any(path.resolve().is_relative_to(root) for root in roots) or path.resolve().parent in [Path(p).resolve() for p in flat_roots])
        if local and path.suffix=='.py':
            try:
                raw=regular(path);row.update(kind='PINNED_LOCAL_PYTHON',sha256=sha(raw),path=str(path))
                tree=ast.parse(raw);package=name if spec['package'] else name.rpartition('.')[0]
                for node in ast.walk(tree):
                    if isinstance(node,ast.Import):queue.extend(a.name for a in node.names)
                    elif isinstance(node,ast.ImportFrom):
                        if node.level:
                            if not package:blockers.append('RELATIVE_IMPORT_CONTEXT_MISSING');continue
                            try:base=importlib.util.resolve_name('.'*node.level+(node.module or ''),package)
                            except (ImportError,ValueError):
                                blockers.append('RELATIVE_IMPORT_CONTEXT_MISSING');continue
                        else:base=node.module
                        if base:
                            queue.append(base)
                            for member in node.names:
                                child=base+'.'+member.name
                                if member.name!='*' and resolve_static(child,search_paths,staged):queue.append(child)
                if any(isinstance(n,ast.Call) and ((isinstance(n.func,ast.Name) and n.func.id in {'eval','exec','__import__'}) or
                    (isinstance(n.func,ast.Attribute) and n.func.attr in {'import_module','spec_from_file_location'})) for n in ast.walk(tree)):
                    blockers.append('DYNAMIC_LOADING_REQUIRES_SEPARATE_MANIFEST_REVIEW')
            except (OSError,ValueError,SyntaxError,UnicodeError):row['kind']='LOCAL_SOURCE_REQUIRES_REVIEW';blockers.append('LOCAL_SOURCE_SCAN_FAILED')
        seen[name]=row
    if missing:blockers.append('UNRESOLVED_TRANSITIVE_IMPORTS_REQUIRE_REVIEW')
    return dict(scope='BOUNDED_STATIC_LOCAL_IMPORT_GRAPH',modules=list(seen.values()),unresolved=sorted(missing),
        blockers=sorted(set(blockers)),package_code_executed=False,external_distributions_locked=False,
        dependency_manifest_fully_reconciled=False,production_ready=False)


def dependency_manifest_review(repo,path):
    repo=Path(repo).resolve();rows=[]
    try:
        manifest=json.loads(regular(Path(path)))
        need(isinstance(manifest,dict),'DEPENDENCY_MANIFEST_REQUIRED')
        for name,expected in manifest.items():
            relative=Path(name)
            need(not relative.is_absolute() and '..' not in relative.parts,'DEPENDENCY_MANIFEST_PATH_INVALID')
            raw=regular(repo/relative)
            rows.append(dict(path=name,hash_matches=isinstance(expected,str) and sha(raw)==expected))
        return dict(status='INSTALLED_DEPENDENCY_PINS_MATCH' if all(r['hash_matches'] for r in rows) else 'INSTALLED_DEPENDENCY_PIN_MISMATCH',
            entries=rows,production_ready=False)
    except (OSError,ValueError,TypeError):return dict(status='DEPENDENCY_MANIFEST_REQUIRES_REVIEW',entries=rows,production_ready=False)
