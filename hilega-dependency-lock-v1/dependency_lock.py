"""Wheel/source verification and fixed dynamic transitive import review. No imports/install."""
import hashlib
import json
from pathlib import Path,PurePosixPath
from zipfile import ZipFile
from email.parser import BytesParser
from runtime_inventory import build


def need(ok,reason):
    if not ok:raise ValueError(reason)


def lock_wheel(path,installed):
    p=Path(path)
    need(p.suffix=='.whl' and p.is_file() and not any(q.is_symlink() for q in [p,*p.absolute().parents]),'REGULAR_WHEEL_REQUIRED')
    need(p.stat().st_size<=5_000_000,'WHEEL_TOO_LARGE')
    with ZipFile(p) as wheel:
        names=wheel.namelist()
        need(len(names)==len(set(names)) and len(names)<500,'WHEEL_DUPLICATE_OR_EXCESS_MEMBERS')
        need(all(not PurePosixPath(n).is_absolute() and '..' not in PurePosixPath(n).parts for n in names),'WHEEL_PATH_INVALID')
        need(sum(x.file_size for x in wheel.infolist())<=10_000_000,'WHEEL_EXPANDED_SIZE_EXCEEDED')
        metadata=[n for n in names if n.endswith('.dist-info/METADATA')]
        need(len(metadata)==1,'UNIQUE_WHEEL_METADATA_REQUIRED')
        data=BytesParser().parsebytes(wheel.read(metadata[0]))
        need(data['Name'].lower().replace('_','-')=='python-dotenv' and data['Version']=='1.2.3','EXACT_DOTENV_WHEEL_REQUIRED')
        requirements=data.get_all('Requires-Dist',[])
        # The runtime uses no optional extras. Additional unconditional dependencies require review.
        need(all('extra ==' in r or 'extra==' in r for r in requirements),'UNREVIEWED_WHEEL_RUNTIME_DEPENDENCY')
        sources={n:hashlib.sha256(wheel.read(n)).hexdigest() for n in names if n.startswith('dotenv/') and n.endswith('.py')}
        need(installed['version_matches'] and sources==installed['installed_source_hashes'],'WHEEL_INSTALLED_SOURCES_DIFFER')
    digest=hashlib.sha256(p.read_bytes()).hexdigest()
    return dict(distribution='python-dotenv',version='1.2.3',wheel_filename=p.name,wheel_sha256=digest,
        installed_python_sources_match=True,optional_extras_not_enabled=True,declared_requirements=requirements,
        requirement='python-dotenv==1.2.3 --hash=sha256:'+digest,package_installed=False)


def transitive_review(repo,stage,dynamic_pins):
    aliases={'preflight_contract_rules':'hilega-production-contract-preview/rules.py',
        'preflight_cash_gate':'hilega-production-real-cash-shadow-gate/gate.py',
        'preflight_market_collector':'hilega-production-contract-preview/run.py',
        'preflight_cash_analysis':'hilega-production-cash-observation/analysis.py',
        'preflight_cash_collector':'hilega-production-cash-observation/run.py',
        'rules':'hilega-production-contract-preview/rules.py','analysis':'hilega-production-cash-observation/analysis.py'}
    for path in aliases.values():
        need(hashlib.sha256((repo/path).read_bytes()).hexdigest()==dynamic_pins[path],'DYNAMIC_TARGET_CHANGED')
    file_map={name:repo/path for name,path in aliases.items()}
    seeds=['closed_application_coordinator_v1','market_lab.hilega_runtime_bootstrap_v1',
        'market_lab.hilega_private_context_v1','market_lab.hilega_provisioning_workflow_v1',*aliases]
    report=build(stage,[stage/'backend',stage,repo/'backend'],seeds=seeds,file_map=file_map)
    need(not report['unresolved_local'],'TRANSITIVE_LOCAL_IMPORTS_UNRESOLVED')
    need(set(report['external_imports'])<={'dotenv'},'UNREVIEWED_EXTERNAL_IMPORT')
    for site in report['dynamic_loading_sites']:
        need(site['module']=='market_lab.hilega_preparation_runtime_v1.evidence'
            and site['call']=='importlib.util.spec_from_file_location','UNREVIEWED_DYNAMIC_LOADER')
        path=Path(report['modules'][site['module']]['path'])
        need(hashlib.sha256(path.read_bytes()).hexdigest()==dynamic_pins['backend/market_lab/hilega_preparation_runtime_v1/evidence.py'],
            'DYNAMIC_LOADER_SOURCE_CHANGED')
    report.update(fixed_dynamic_transitive_imports_reviewed=True,review_scope='EXPLICIT_CANDIDATE_AND_FIXED_COLLECTOR_IMPORT_GRAPH',
        arbitrary_dynamic_loading_approved=False,production_activation_approved=False)
    return report
