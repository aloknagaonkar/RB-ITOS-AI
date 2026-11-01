import json
from unittest.mock import patch
import pytest
from readiness import sha
from effective_environment import environment_review,APP,ADAPTER,DEFAULTS


@pytest.fixture
def setup(tmp_path):
    repo=tmp_path/'repo';home=tmp_path/'home';repo.mkdir();folder=home/'hilega-persistent-supervision-stage-v1';folder.mkdir(parents=True)
    env=repo/'.env';env.write_text('UPSTOX_ACCESS_TOKEN=must-not-export\nHILEGA_PREPARATION_ADAPTER_DB=data/selected.sqlite\n')
    config=dict(root=str(repo),env_sha256=sha(env.read_bytes()),startup={'production-source-worker':dict(
        argv=[str(repo/'.venv/bin/python'),'-u',str(repo/'scripts/hilega_production_simulator_bridge.py'),'--watch'],
        env={APP:'data/application.sqlite'})})
    path=folder/'config-private.json';path.write_text(json.dumps(config))
    with patch('effective_environment.supervisor_review',return_value=({'approval_hashes_match':True},{})):
        yield repo,home,path,env,config


def test_pinned_env_path_is_selected_without_exporting_values(setup):
    repo,home,_,_,_=setup;report,paths=environment_review(repo,home)
    assert report['effective_database_paths_confirmed'] is True
    assert paths[ADAPTER]==repo/'data/selected.sqlite'
    assert 'must-not-export' not in json.dumps(report)
    assert report['actual_running_process_environment_verified'] is False


def test_captured_environment_wins_over_env_file(setup):
    repo,home,path,_,config=setup;config['startup']['production-source-worker']['env'][ADAPTER]='data/captured.sqlite';path.write_text(json.dumps(config))
    report,paths=environment_review(repo,home)
    assert paths[ADAPTER]==repo/'data/captured.sqlite' and report['environment_hash_revalidated'] is True


def test_changed_env_hash_blocks_confirmation(setup):
    repo,home,_,env,_=setup;env.write_text(env.read_text()+'NEW=changed\n');before=env.read_bytes()
    report,paths=environment_review(repo,home)
    assert report['status']=='BLOCKED' and not paths and env.read_bytes()==before


def test_relevant_interpolation_is_not_resolved_against_review_shell(setup):
    repo,home,path,env,config=setup;env.write_text('HILEGA_PREPARATION_ADAPTER_DB=${HOME}/adapter.sqlite\n')
    config['env_sha256']=sha(env.read_bytes());path.write_text(json.dumps(config))
    report,paths=environment_review(repo,home)
    assert report['status']=='BLOCKED' and not paths


def test_reviewed_default_is_used_only_when_setting_is_absent(setup):
    repo,home,path,env,config=setup;env.write_text('UNRELATED=value\n');config['env_sha256']=sha(env.read_bytes());path.write_text(json.dumps(config))
    report,paths=environment_review(repo,home)
    assert paths[ADAPTER]==repo/DEFAULTS[ADAPTER]
    assert report['database_path_provenance'][ADAPTER]=='REVIEWED_SOURCE_DEFAULT'


def test_different_env_file_is_not_covered_by_root_env_hash(setup):
    repo,home,path,_,config=setup;config['startup']['production-source-worker']['argv']+=['--env-file','other.env'];path.write_text(json.dumps(config))
    report,paths=environment_review(repo,home)
    assert report['status']=='BLOCKED' and not paths


def test_empty_captured_value_does_not_fall_back_to_env_file(setup):
    repo,home,path,_,config=setup;config['startup']['production-source-worker']['env'][ADAPTER]='';path.write_text(json.dumps(config))
    report,paths=environment_review(repo,home)
    assert report['status']=='BLOCKED' and not paths


def test_same_database_selection_is_rejected(setup):
    repo,home,path,_,config=setup;config['startup']['production-source-worker']['env'][ADAPTER]=config['startup']['production-source-worker']['env'][APP];path.write_text(json.dumps(config))
    report,paths=environment_review(repo,home)
    assert report['status']=='BLOCKED' and not paths
