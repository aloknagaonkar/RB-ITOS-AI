"""Read-only dependency review and proposed registration contract; no runtime activation."""
import ast
import hashlib
import importlib.metadata
import json
from pathlib import Path


def need(ok,reason):
    if not ok:raise ValueError(reason)


def regular(path):
    p=Path(path)
    need(p.is_absolute() and p.is_file() and not any(q.is_symlink() for q in [p,*p.parents]),'REGULAR_DEPENDENCY_REQUIRED')
    return p.read_bytes()


def review_dynamic(repo,pins):
    verified={}
    for relative,digest in pins.items():
        p=Path(relative);need(not p.is_absolute() and '..' not in p.parts,'RELATIVE_DEPENDENCY_PATH_REQUIRED')
        raw=regular(repo/p);need(hashlib.sha256(raw).hexdigest()==digest,'REVIEWED_DYNAMIC_DEPENDENCY_CHANGED: '+relative)
        verified[relative]=digest
    manifest_path=repo/'backend/market_lab/hilega_preparation_runtime_v1/dependencies.json'
    manifest=json.loads(regular(manifest_path))
    for relative,digest in manifest.items():
        p=Path(relative);need(not p.is_absolute() and '..' not in p.parts,'RELATIVE_DEPENDENCY_PATH_REQUIRED')
        need(pins.get(relative)==digest,'DYNAMIC_MANIFEST_BINDING_CHANGED')
    required={'hilega-production-contract-preview/rules.py','hilega-production-contract-preview/run.py',
        'hilega-production-cash-observation/analysis.py','hilega-production-cash-observation/run.py',
        'hilega-production-real-cash-shadow-gate/gate.py'}
    need(required<=set(manifest),'FIXED_DYNAMIC_TARGETS_REQUIRED')
    return dict(status='REVIEWED_FIXED_TARGET_HASHES_MATCH',verified_files=verified,
        fixed_dynamic_targets=sorted(required),modules_executed=False,broker_calls_issued=False)


def distribution_snapshot(expected_version,distribution=None):
    dist=distribution or importlib.metadata.distribution('python-dotenv')
    rows={}
    for relative in dist.files or []:
        name=str(relative)
        if not (name.startswith('dotenv/') and name.endswith('.py')):continue
        p=Path(dist.locate_file(relative)).absolute()
        rows[name]=hashlib.sha256(regular(p)).hexdigest()
    need(rows,'DOTENV_INSTALLED_SOURCE_INVENTORY_REQUIRED')
    return dict(distribution='python-dotenv',expected_version=expected_version,installed_version=dist.version,
        version_matches=dist.version==expected_version,installed_source_hashes=rows,
        artifact_kind='OBSERVED_INSTALLED_SOURCE_SNAPSHOT',wheel_artifact_hash_locked=False,
        package_installed_or_modified=False)


def registration_plan(stage,manifest,dynamic,external):
    need(dynamic['status']=='REVIEWED_FIXED_TARGET_HASHES_MATCH','DYNAMIC_REVIEW_REQUIRED')
    return dict(scope='PROPOSED_CLOSED_RUNTIME_REGISTRATION_ONLY',stage=str(stage),staged_runtime_hashes=manifest,
        dynamic_fixed_targets_verified=True,external_version_matches=external['version_matches'],
        dependency_manifest_fully_reconciled=False,live_apply_available=False,
        public_registration_required=['RUNTIME_BUNDLE_MANIFEST_DIGEST','APPROVED_PRIVATE_CONTEXT_DIGEST',
            'APPLICATION_AND_ADAPTER_PATHS','JOURNAL_PATH','SOURCE_LEASE_AND_SIGNED_OWNER_BINDING'],
        bootstrap_requires_explicit_existing_store=True,environment_activation_available=False,
        fresh_seed_policy='BIND_ONLY_GENUINELY_FRESH_SIGNED_UNSENT_PREPARATION_AFTER_TRUST_AND_RUNTIME_APPROVAL',
        controller_resume_implemented=False,production_authority_provisioned=False,
        production_execution_enabled=False,production_ready=False,
        remaining=['EXTERNAL_WHEEL_HASH_LOCK_AND_TRANSITIVE_DYNAMIC_IMPORT_REVIEW',
            'REVIEWED_RUNTIME_ASSEMBLY_AND_SUPERVISOR_APPROVAL',
            'TRUSTED_AUTHORITY_AND_BROKER_READ_VALIDATION','FEES_CASH_AND_PARTIAL_FILL_POLICIES',
            'FULL_RELEASE_REGRESSION_AND_CLOSED_ROLLOUT',
            'APPROVED_FRESH_SEED_ENROLLMENT_AND_CONTROLLED_LIVE_PILOT'])
