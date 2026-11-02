import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
import pytest
from release_review import review_dynamic,distribution_snapshot,registration_plan


def test_dynamic_review_rejects_changed_file(tmp_path):
    (tmp_path/'x.py').write_text('pass')
    with pytest.raises(ValueError,match='DEPENDENCY_CHANGED'):review_dynamic(tmp_path,{'x.py':'0'*64})


def test_dynamic_review_rejects_parent_traversal(tmp_path):
    with pytest.raises(ValueError,match='RELATIVE_DEPENDENCY'):review_dynamic(tmp_path,{'../outside.py':'0'*64})


def test_installed_distribution_snapshot_reads_sources_without_import(tmp_path):
    p=tmp_path/'dotenv';p.mkdir();(p/'__init__.py').write_text('raise RuntimeError("never import")')
    dist=SimpleNamespace(files=['dotenv/__init__.py'],version='1.2.3',locate_file=lambda n:tmp_path/n)
    result=distribution_snapshot('1.2.3',dist)
    assert result['version_matches'];assert result['wheel_artifact_hash_locked'] is False
    assert result['installed_source_hashes']['dotenv/__init__.py']==hashlib.sha256((p/'__init__.py').read_bytes()).hexdigest()


def test_distribution_mismatch_is_reported_without_install(tmp_path):
    p=tmp_path/'dotenv';p.mkdir();(p/'__init__.py').write_text('')
    dist=SimpleNamespace(files=['dotenv/__init__.py'],version='other',locate_file=lambda n:tmp_path/n)
    assert distribution_snapshot('1.2.3',dist)['version_matches'] is False


def test_registration_stays_closed_and_requires_fresh_seed():
    result=registration_plan(Path('/stage'),{},dict(status='REVIEWED_FIXED_TARGET_HASHES_MATCH'),dict(version_matches=True))
    assert result['live_apply_available'] is False and result['production_execution_enabled'] is False
    assert result['controller_resume_implemented'] is False and result['dependency_manifest_fully_reconciled'] is False
    assert 'GENUINELY_FRESH' in result['fresh_seed_policy']


def test_unreviewed_dynamic_loader_cannot_make_registration_plan():
    with pytest.raises(ValueError,match='DYNAMIC_REVIEW_REQUIRED'):
        registration_plan(Path('/stage'),{},dict(status='UNKNOWN'),dict(version_matches=True))
