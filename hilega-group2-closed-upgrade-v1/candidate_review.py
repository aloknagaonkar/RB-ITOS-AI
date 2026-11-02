"""Read-only candidate integrity and recovery compatibility review. No imports from candidate."""
import argparse
import hashlib
import json
from pathlib import Path


def need(ok, reason):
    if not ok:
        raise ValueError(reason)


def read(path):
    path = Path(path).absolute()
    need(not any(p.is_symlink() for p in (path, *path.parents)) and path.is_file(), 'REGULAR_FILE_REQUIRED')
    return path.read_bytes()


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--review', type=Path, required=True)
    parser.add_argument('--approve-context-sha256', required=True)
    args = parser.parse_args()
    folder = args.review.absolute()
    result = json.loads(read(folder / 'RESULT.json'))
    need(result['candidate_test_batch_complete'] is True and result['targeted_cases'] == 74
         and result['failed'] == result['skipped'] == 0, 'PASSING_COMBINED_RECEIPT_REQUIRED')
    context_raw = read(folder / 'CONTEXT-ADOPTION-PLAN.json')
    need(digest(context_raw) == args.approve_context_sha256 == result['context_adoption_plan_sha256'], 'CONTEXT_DIGEST_MISMATCH')
    context = json.loads(context_raw)
    need(context['live_arming_permitted'] is False and context['live_enrollment_permitted'] is False
         and context['hard_gate_change_available'] is False, 'CLOSED_REVIEW_REQUIRED')
    need(digest(read(folder / 'AUTHORITY-REVIEW-REQUEST.json')) == context['authority_review_request_sha256'], 'AUTHORITY_REVIEW_CHANGED')
    bundle = Path(result['candidate_folder'])
    need(bundle.is_absolute() and bundle == folder / 'candidate', 'EXACT_CANDIDATE_PATH_REQUIRED')
    raw = read(bundle / 'RELEASE-MANIFEST.json')
    need(digest(raw) == context['release_manifest_sha256'] == result['candidate_changes']['candidate_release_sha256'], 'CANDIDATE_MANIFEST_CHANGED')
    manifest = json.loads(raw)
    for name, expected in manifest['files'].items():
        rel = Path(name)
        need(not rel.is_absolute() and '..' not in rel.parts, 'UNSAFE_MANIFEST_PATH')
        need(digest(read(bundle / rel)) == expected, 'CANDIDATE_FILE_CHANGED: ' + name)
    actual = set()
    for path in bundle.rglob('*'):
        need(not path.is_symlink(), 'CANDIDATE_SYMLINK')
        if path.is_file():
            actual.add(path.relative_to(bundle).as_posix())
    need(actual == set(manifest['files']) | {'RELEASE-MANIFEST.json'}, 'UNMANIFESTED_CANDIDATE_FILE')
    print(json.dumps(dict(
        status='STATIC_CANDIDATE_DEPLOYMENT_REVIEW_ONLY',
        candidate_files_verified=len(manifest['files']), context_and_authority_review_hashes_verified=True,
        prior_74_case_receipt_verified=True, prior_tests_reexecuted=False,
        installed_recovery_compatibility='REQUIRES_NEW_EXACT_RELEASE_BINDING_REVIEW',
        remaining_work=[
            'VERIFY_CURRENT_INSTALLED_STATE_AND_RECOVERY_CONFIG_BEFORE_PLANNING',
            'REHEARSE_NEW_RELEASE_RECOVERY_BINDING_WITH_FACTORY_DISABLED',
            'CREATE_EXACT_INSTALL_BACKUP_AND_ROLLBACK_PLAN',
            'RESOLVE_BROKER_TIMESTAMP_CONTRACT_BEFORE_REAL_EVIDENCE_ADOPTION',
            'INDEPENDENT_AUTHORITY_ORDER_POLICY_AND_FEE_RELEASE_REVIEW',
        ],
        live_apply_available=False, production_authority_provisioned=False,
        group2_complete=False, production_execution_enabled=False,
        application_database_opened=False, service_commands_issued=False,
        installed_sources_modified=False,
    ), indent=2))


if __name__ == '__main__':
    main()
