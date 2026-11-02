"""Combined Group 1 assembly and explicit production change proposal. No live apply."""
import hashlib
import json
from pathlib import Path
from assembly import regular,verify,need
from runtime_inventory import build
from ast_compat import reviewed_dump


def sha(raw):return hashlib.sha256(raw).hexdigest()


def expand_worker(repo,release):
    aliases={'_group1_worker':'scripts/hilega_production_simulator_bridge.py',
        'preflight_contract_rules':'hilega-production-contract-preview/rules.py',
        'preflight_cash_gate':'hilega-production-real-cash-shadow-gate/gate.py',
        'preflight_market_collector':'hilega-production-contract-preview/run.py',
        'preflight_cash_analysis':'hilega-production-cash-observation/analysis.py',
        'preflight_cash_collector':'hilega-production-cash-observation/run.py',
        'rules':'hilega-production-contract-preview/rules.py','analysis':'hilega-production-cash-observation/analysis.py'}
    mapped={name:release/path for name,path in aliases.items()}
    graph=build(release/'runtime',[release/'backend',release/'runtime',repo/'backend'],seeds=list(aliases),file_map=mapped)
    need(not graph['unresolved_local'],'WORKER_LOCAL_IMPORTS_UNRESOLVED')
    (release.parent/'WORKER-IMPORT-GRAPH.json').write_text(json.dumps(graph,indent=2)+'\n')
    need(set(graph['external_imports'])<={'dotenv','pydantic'},'ADDITIONAL_WORKER_DISTRIBUTIONS_REQUIRE_LOCK: '+', '.join(graph['external_imports']))
    inputs={}
    for name,row in graph['modules'].items():
        path=Path(row['path']);raw=regular(path);need(sha(raw)==row['sha256'],'WORKER_IMPORT_CHANGED')
        inputs[str(path)]=row['sha256']
        if name in aliases:continue
        if name=='market_lab' or name.startswith('market_lab.'):
            rel=Path('backend',*name.split('.'))
            rel=rel/'__init__.py' if path.name=='__init__.py' else rel.with_suffix('.py')
        else:
            need('.' not in name,'UNREVIEWED_WORKER_IMPORT_LAYOUT');rel=Path('runtime',name+'.py')
        target=release/rel
        if target.exists():need(target.read_bytes()==raw,'WORKER_DEPENDENCY_COLLISION')
        else:target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(raw)
    need(not (release/'runtime/market_lab.py').exists(),'FLATTENED_PACKAGE_SHADOWS_BACKEND')
    need((release/'backend/market_lab/__init__.py').is_file(),'BUNDLED_MARKET_LAB_PACKAGE_REQUIRED')
    graph['input_hashes']=inputs
    return graph


def launcher_text():
    return '''"""Closed registered worker launcher. No execution factory activation."""
from pathlib import Path
import hashlib
import runpy
import sys
root=Path(__file__).resolve().parent
sys.path.insert(0,str(root/'backend'));sys.path.insert(0,str(root/'runtime'))
registration=root/'CLOSED-REGISTRATION.json'
sys.argv.extend(['--closed-registration',str(registration),'--closed-registration-sha256',hashlib.sha256(registration.read_bytes()).hexdigest()])
runpy.run_path(str(root/'scripts/hilega_production_simulator_bridge.py'),run_name='__main__')
'''


def proposal(repo,release,manifest_digest,supervisor):
    need(supervisor.get('approval_hashes_match') is True,'SUPERVISOR_REVIEW_REQUIRED')
    old=regular(repo/'scripts/hilega_production_simulator_bridge.py')
    return dict(scope='PROPOSED_CLOSED_SOURCE_WORKER_BUNDLE_DEPLOYMENT',repo=str(repo),bundle=str(release),
        release_manifest_sha256=manifest_digest,
        installed_worker=dict(path='scripts/hilega_production_simulator_bridge.py',old_sha256=sha(old)),
        existing_supervisor_bindings_match=True,new_release_approved=False,live_apply_available=False,
        source_route='CLOSED_PREPARATION_ONLY',execution_factory_configured=False,
        required_before_apply=['FULL_SERVICE_IMPORT_AND_DISTRIBUTION_RECONCILIATION',
            'EXACT_INSTALL_DESTINATION_AND_WORKER_WRAPPER_REVIEW','NEW_RELEASE_SUPERVISOR_AND_COMPANION_BINDINGS',
            'FULL_RELEASE_REGRESSION','APPROVED_SERVICE_QUIESCENCE_AND_REAL_CODE_DATABASE_BACKUPS',
            'LIVE_EMPTY_PAUSED_BASELINE_RECHECK','EXACT_PLAN_APPROVAL'],
        rollback_policy=dict(restore_verified_code_only=True,stop_affected_services_before_restore=True,
            restore_previously_active_service_set=True,recheck_new_lease_and_advancing_heartbeat=True,
            automatic_live_database_rewind=False,retain_database_backups=True),
        controller_resume_permitted=False,production_execution_enabled=False,production_ready=False)


def stage_runtime_policy(repo,release,folder):
    import ast
    pins=json.loads(regular(folder/'POLICY-PINS.json'))
    raw=regular(repo/'backend/market_lab/hilega_combined_policy_v1.py')
    need(sha(raw)==pins['policy_sha256'],'REVIEWED_STRATEGY_POLICY_CHANGED')
    research=regular(repo/'hilega_existing_ema10_wma_exception_40_60_last10_research.py').decode()
    node=next(n for n in ast.parse(research).body if isinstance(n,ast.FunctionDef) and n.name=='exception_allows')
    need(reviewed_dump(node)==pins['exception_function_ast'],'REVIEWED_EXCEPTION_FUNCTION_CHANGED')
    runtime=regular(folder/'runtime_rsi_exception_v1.py')
    copied=next(n for n in ast.parse(runtime).body if isinstance(n,ast.FunctionDef) and n.name=='exception_allows')
    need(reviewed_dump(copied)==reviewed_dump(node),'EXCEPTION_FUNCTION_PARITY_REQUIRED')
    before='import hilega_existing_ema10_wma_exception_40_60_last10_research as exception'
    text=raw.decode();need(text.count(before)==1,'EXACT_RESEARCH_IMPORT_ANCHOR_REQUIRED')
    text=text.replace(before,'from . import hilega_runtime_rsi_exception_v1 as exception',1)
    target=release/'backend/market_lab/hilega_combined_policy_v1.py'
    target.write_text(text);(target.parent/'hilega_runtime_rsi_exception_v1.py').write_bytes(runtime)
    return dict(original_policy_sha256=sha(raw),candidate_policy_sha256=sha(text.encode()),
        exception_function_ast_identical=True,research_module_required_by_candidate=False,installed_policy_modified=False)
