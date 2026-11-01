"""Read-only effective environment and proposed closed-release contract. No approval writes."""
import json
from pathlib import Path
from io import StringIO
from readiness import regular,sha,need,supervisor_review,baseline

APP='HILEGA_PRODUCTION_SIM_DB'
ADAPTER='HILEGA_PREPARATION_ADAPTER_DB'
DEFAULTS={APP:'data/research/hilega-production-workspace/sim.sqlite',
    ADAPTER:'data/research/hilega-broker-adapter-closed/adapter.sqlite'}


def environment_review(repo,home):
    repo=Path(repo).resolve();home=Path(home).resolve()
    report=dict(status='BLOCKED',environment_hash_revalidated=False,effective_database_paths_confirmed=False,
        private_values_exported=False,approvals_modified=False,services_changed=False,
        actual_running_process_environment_verified=False)
    paths={}
    try:
        supervisor,_=supervisor_review(repo,home)
        need(supervisor['approval_hashes_match'],'SUPERVISOR_APPROVAL_MISMATCH')
        config=json.loads(regular(home/'hilega-persistent-supervision-stage-v1/config-private.json'))
        item=config['startup']['production-source-worker'];argv=item['argv'];captured=item['env']
        files=[]
        for i,value in enumerate(argv):
            if value=='--env-file':
                need(i+1<len(argv),'ENV_FILE_ARGUMENT_MISSING');files.append(argv[i+1])
            elif isinstance(value,str) and value.startswith('--env-file='):files.append(value.split('=',1)[1])
        need(len(files)<=1,'AMBIGUOUS_ENV_FILE_ARGUMENT')
        env_file=Path(files[0]) if files else Path('.env')
        env_file=env_file if env_file.is_absolute() else repo/env_file
        need(env_file.resolve()==repo/'.env','ENV_FILE_NOT_COVERED_BY_SUPERVISOR_PIN')
        raw=regular(env_file)
        need(isinstance(config.get('env_sha256'),str) and sha(raw)==config['env_sha256'],'SUPERVISOR_ENVIRONMENT_HASH_CHANGED')
        from dotenv import dotenv_values
        # Parse privately; reject relevant interpolation rather than using this shell's environment.
        values=dotenv_values(stream=StringIO(raw.decode()),interpolate=False)
        provenance={}
        for key in (APP,ADAPTER):
            if key in captured:
                value=captured[key];source='SUPERVISOR_CAPTURED_ENVIRONMENT'
            elif values.get(key) is not None:
                value=values[key];source='PINNED_ENV_FILE_OVERRIDE_FALSE'
            else:value=DEFAULTS[key];source='REVIEWED_SOURCE_DEFAULT'
            need(isinstance(value,str) and value.strip() and '${' not in value and '\x00' not in value,
                 'DATABASE_SETTING_REQUIRES_INTERPOLATION_OR_VALUE_REVIEW')
            path=Path(value);path=path if path.is_absolute() else repo/path
            need(not any(p.is_symlink() for p in [path,*path.parents]),'DATABASE_PATH_SYMLINK_FORBIDDEN')
            paths[key]=path;provenance[key]=source
        need(paths[APP].resolve()!=paths[ADAPTER].resolve(),'DISTINCT_DATABASES_REQUIRED')
        # Recheck both files after parsing so the result cannot mix changed revisions.
        need(regular(env_file)==raw and json.loads(regular(home/'hilega-persistent-supervision-stage-v1/config-private.json'))==config,
             'CONFIGURATION_CHANGED_DURING_REVIEW')
        report.update(status='PINNED_STARTUP_ENVIRONMENT_REVIEWED',environment_hash_revalidated=True,
            effective_database_paths_confirmed=True,path_selection_basis='APPROVED_STARTUP_CONFIGURATION_AND_PINNED_ENV_FILE',
            database_path_provenance=provenance,default_uses_override_false=True,
            new_release_approved=False,production_ready=False)
    except (OSError,ValueError,KeyError,TypeError,UnicodeError):
        report['reason']='EFFECTIVE_ENVIRONMENT_REQUIRES_REVIEW';paths={}
    return report,paths


def combined_review(repo,home,stage,stage_pins):
    report,paths=environment_review(repo,home)
    capture=baseline(repo,{},application_db=paths[APP],adapter_db=paths[ADAPTER]) if paths else dict(
        status='BASELINE_NOT_CONFIRMED',blockers=['EFFECTIVE_ENVIRONMENT_NOT_CONFIRMED'],live_database_inspected=False,migration_approved=False)
    changes=[]
    for name in ('scripts/hilega_production_simulator_bridge.py',
        'backend/market_lab/hilega_preparation_runtime_v1/source.py',
        'backend/market_lab/hilega_exclusive_closed_route_v1.py'):
        new=regular(Path(stage)/name);need(sha(new)==stage_pins[name],'STAGED_RELEASE_CHANGED')
        old=Path(repo)/name
        old_sha=sha(regular(old)) if old.exists() else None
        changes.append(dict(target=name,current_sha256=old_sha,proposed_sha256=sha(new)))
    contract=dict(model='HILEGA_PROPOSED_CLOSED_RELEASE_CONTRACT_V1',status='REVIEW_ONLY_NOT_APPROVED',
        files=changes,environment_pin_matches=report['environment_hash_revalidated'],
        startup_path_review_passed=report['effective_database_paths_confirmed'],
        existing_baseline_blockers=capture.get('blockers',[]),
        actual_process_environment_verified=False,old_workers_quiesced=False,
        code_and_database_backups_created=False,new_release_approved=False,
        dependency_manifest_fully_reconciled=False,live_apply_available=False,production_execution_enabled=False)
    return report,capture,contract
