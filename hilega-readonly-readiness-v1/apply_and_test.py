"""Combined VM read-only readiness capture and synthetic validation. No apply command."""
import argparse
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
from readiness import regular,sha,supervisor_review,baseline,transitive_inventory,dependency_manifest_review


def need(ok,reason):
    if not ok:raise SystemExit('STOP: '+reason)


def checked(folder):
    manifest=json.loads(regular(folder/'MANIFEST.json'))
    for name,expected in manifest.items():
        relative=Path(name);need(not relative.is_absolute() and '..' not in relative.parts,'invalid manifest path')
        need(sha(regular(folder/relative))==expected,'PACKAGE_CHANGED: '+str(folder/relative))
    return manifest


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo',type=Path,default=Path.cwd())
    parser.add_argument('--application-db',type=Path,help='Explicit existing local application database; opened query-only')
    parser.add_argument('--adapter-db',type=Path,help='Explicit existing closed adapter database; opened query-only')
    parser.add_argument('--skip-database-baseline',action='store_true')
    parser.add_argument('--integration',action='store_true',help='226 cases including previous 212')
    args=parser.parse_args();repo=args.repo.resolve();folder=Path(__file__).resolve().parent
    names=('hilega-closed-release-v2','hilega-exclusive-route-v1','hilega-durable-coordinator-v1','hilega-second-application-cycle-v3',
        'hilega-history-aware-preparation-v1','hilega-application-cycle-close-v1')
    previous=[repo/n for n in names];v2,route,coordinator,second,preparation,base=previous
    directories=[folder,*previous];manifests={d:checked(d) for d in directories}
    pins=json.loads(regular(folder/'BASELINE_PINS.json'))
    for name,expected in pins.items():need(sha(regular(repo/name))==expected,'REVIEWED_SOURCE_CHANGED: '+name)
    evidence=v2/'VM-VALIDATION.json';prior=json.loads(regular(evidence))
    need(prior.get('status')=='PASS_TARGETED_ONLY' and prior.get('collected_cases')==212
        and prior.get('failed')==0 and prior.get('skipped')==0 and prior.get('pytest_exit_code')==0
        and prior.get('broader_integration_reexecuted') is True and prior.get('direct_unresolved_imports')==0
        and prior.get('pinned_application_sources_unchanged') is True
        and prior.get('previous_candidate_sources_unchanged') is True
        and prior.get('staged_sources_unchanged') is True
        and all(prior.get(k) is False for k in ('production_execution_enabled','runtime_deployed','production_ready')),
        'successful 212-case closed release checkpoint required')
    candidate=Path(prior['stage']);review=Path(prior['review_folder'])
    need(candidate.is_absolute() and review.is_absolute() and candidate.parent==review,'prior stage binding changed')
    stage_pins=json.loads(regular(review/'STAGED-MANIFEST.json'))
    for name,expected in stage_pins.items():
        p=Path(name);need(not p.is_absolute() and '..' not in p.parts,'invalid stage path')
        need(sha(regular(candidate/p))==expected,'VERIFIED_STAGE_CHANGED')
    mappings=json.loads(regular(review/'STAGED-MODULE-MAP.json'));staged={}
    for name,row in mappings.items():
        relative=Path(row['relative_path']);need(not relative.is_absolute() and '..' not in relative.parts,'invalid staged mapping')
        path=candidate/relative;need(sha(regular(path))==row['sha256']==stage_pins[str(relative)],'STAGED_MAPPING_CHANGED')
        staged[name]=path
    for d in directories:
        for p in d.glob('*.py'):compile(p.read_bytes(),str(p),'exec')
    output=Path(tempfile.mkdtemp(prefix='hilega-readonly-readiness-',dir=repo))
    supervisor,context=supervisor_review(repo,Path.home())
    (output/'SUPERVISOR-REVIEW.json').write_text(json.dumps(supervisor,indent=2)+'\n')
    captured=baseline(repo,context,application_db=args.application_db,adapter_db=args.adapter_db) if not args.skip_database_baseline else dict(status='SKIPPED',snapshots=[],blockers=['DATABASE_BASELINE_SKIPPED'],live_database_inspected=False,migration_approved=False)
    (output/'DATABASE-BASELINE.json').write_text(json.dumps(captured,indent=2)+'\n')
    paths=[candidate/'backend',*previous,repo/'backend',repo/'tests',repo,Path.home(),*[Path(p) for p in sys.path if p]]
    graph=transitive_inventory(list(staged),paths,[candidate,*previous,repo/'backend'],staged,flat_roots=[Path.home()])
    (output/'TRANSITIVE-LOCAL-DEPENDENCIES.json').write_text(json.dumps(graph,indent=2)+'\n')
    installed=dependency_manifest_review(repo,repo/'backend/market_lab/hilega_preparation_runtime_v1/dependencies.json')
    (output/'INSTALLED-DEPENDENCY-PINS.json').write_text(json.dumps(installed,indent=2)+'\n')
    selected=[]
    if args.integration:
        selected += [str(route/'test_exclusive_closed_route_v1.py'),str(coordinator/'test_closed_application_coordinator_v1.py'),
            str(second/'test_second_application_cycle_v1.py'),str(preparation/'test_history_aware_preparation_v1.py')]
        selected += [str(base/n) for n in ('test_authenticated_handoff_v1.py','test_durable_closed_handoff_v1.py',
            'test_existing_request_attempt_v1.py','test_application_lifecycle_candidate_v1.py','test_application_cycle_close_v1.py')]
        selected.append(str(v2/'test_closed_release.py'))
    selected.append(str(folder/'test_readiness.py'))
    environment=dict(os.environ);environment['PYTHONPATH']=os.pathsep.join(map(str,[*directories,repo/'backend',repo/'tests',repo]))
    environment['HILEGA_EXCLUSIVE_TEST_STAGE']=str(candidate);environment['HILEGA_RELEASE_STAGE']=str(candidate)
    with tempfile.TemporaryDirectory(prefix='hilega-readiness-tests-') as temporary:
        junit=Path(temporary)/'junit.xml'
        code=subprocess.run([sys.executable,'-m','pytest',*selected,'-q','--junitxml='+str(junit)],cwd=repo,env=environment).returncode
        cases=list(ET.parse(junit).getroot().iter('testcase')) if junit.is_file() else []
        failed=sum(c.find('failure') is not None or c.find('error') is not None for c in cases)
        skipped=sum(c.find('skipped') is not None for c in cases)
    unchanged=all(sha(regular(repo/n))==v for n,v in pins.items())
    packages=all(sha(regular(d/n))==v for d,m in manifests.items() for n,v in m.items())
    stage_ok=all(sha(regular(candidate/n))==v for n,v in stage_pins.items())
    expected=226 if args.integration else 14
    passed=code==0 and len(cases)==expected and failed==skipped==0 and unchanged and packages and stage_ok
    blockers=list(graph['blockers'])+list(captured.get('blockers',[]))
    if not supervisor['approval_hashes_match']:blockers.append('SUPERVISOR_APPROVAL_BINDINGS_REQUIRE_REVIEW')
    if installed['status']!='INSTALLED_DEPENDENCY_PINS_MATCH':blockers.append('INSTALLED_DEPENDENCY_PINS_REQUIRE_REVIEW')
    blockers += ['ENVIRONMENT_AND_NEW_RELEASE_APPROVAL_NOT_RECONCILED','EXTERNAL_DISTRIBUTIONS_NOT_LOCKED',
        'SIGNED_OWNERSHIP_AND_BROKER_BASELINE_NOT_VERIFIED','OLD_WORKER_QUIESCENCE_AND_REAL_BACKUPS_PENDING',
        'ACTUAL_MANAGED_CLOSED_STARTUP_AND_ROLLBACK_PENDING','EXECUTION_FACTORY_AUTHORITY_AND_POLICIES_PENDING',
        'BROKER_VALIDATION_FEES_CASH_HANDLING_PENDING','FULL_RELEASE_REGRESSION_PENDING']
    report=dict(status='PASS_TARGETED_ONLY' if passed else 'FAIL_OR_INCOMPLETE',scope='READ_ONLY_SUPERVISOR_TRANSITIVE_DEPENDENCIES_AND_DATABASE_BASELINE',
        collected_cases=len(cases),failed=failed,skipped=skipped,pytest_exit_code=code,
        broader_integration_reexecuted=args.integration,full_regression_reexecuted=False,prior_integration_cases_passed=212,
        prior_report_sha256=sha(regular(evidence)),pinned_application_sources_unchanged=unchanged,
        previous_candidate_sources_unchanged=packages,staged_sources_unchanged=stage_ok,
        supervisor_approval_hashes_match=supervisor['approval_hashes_match'],
        transitive_local_inventory_created=True,transitive_unresolved_imports=len(graph['unresolved']),
        installed_dependency_pins_match=installed['status']=='INSTALLED_DEPENDENCY_PINS_MATCH',
        dependency_manifest_fully_reconciled=False,database_baseline_status=captured['status'],
        live_database_inspected=captured['live_database_inspected'],baseline_sql_mutations_issued=False,
        ownership_migration_approved=False,review_folder=str(output),deployment_blockers=sorted(set(blockers)),
        approvals_modified=False,environment_values_exported=False,service_control_commands_issued=False,
        running_service_hook_installed=False,production_execution_session_factory_configured=False,
        actual_broker_network_validated=False,fees_complete=False,broker_cash_release_implemented=False,
        installed_sources_modified=False,services_changed=False,production_execution_enabled=False,
        runtime_deployed=False,production_ready=False)
    destination=folder/'VM-VALIDATION.json';destination.write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(report,indent=2));print('Report:',destination)
    return 0 if passed else 1

if __name__=='__main__':raise SystemExit(main())
