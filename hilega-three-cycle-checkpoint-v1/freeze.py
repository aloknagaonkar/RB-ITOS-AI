"""Freeze the reported 120-case fixture checkpoint without opening databases."""
import argparse
import ast
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import tempfile


def need(ok, reason):
    if not ok:
        raise SystemExit('STOP: '+reason)


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo', type=Path, default=Path.cwd())
    args = parser.parse_args()
    repo = args.repo.resolve()
    package = Path(__file__).resolve().parent
    home = Path.home()
    need((repo/'backend/market_lab').is_dir(), '--repo must identify RB-ITOS-AI')
    manifest = json.loads((package/'MANIFEST.json').read_text())
    for name, expected in manifest['files'].items():
        path = package/name
        need(path.is_file() and not path.is_symlink(), 'regular package file required: '+name)
        need(digest(path.read_bytes()) == expected, 'package checksum changed: '+name)
    report_path = repo/'hilega-third-reference-retirement-v1/VM-VALIDATION.json'
    need(report_path.is_file() and not report_path.is_symlink(), '120-case VM report required')
    report_raw = report_path.read_bytes()
    report = json.loads(report_raw)
    need(report.get('status') == 'PASS' and report.get('pytest_exit_code') == 0
         and type(report.get('collected_cases')) is int
         and report['collected_cases'] == 120
         and report.get('failed') == 0 and report.get('skipped') == 0
         and report.get('scope') == 'SYNTHETIC_FIXTURE_THIRD_REFERENCE_RETIREMENT',
         'expected passing 120-case fixture report required')
    for flag in ('production_execution_enabled', 'runtime_deployed', 'production_ready'):
        need(report.get(flag) is False, 'unexpected report authority: '+flag)
    need(report.get('third_fixture_references_retired') is True
         and report.get('fourth_entry_admission_implemented') is False,
         'unexpected lifecycle checkpoint')
    snapshots = {}
    for name in manifest['candidate_files']:
        path = home/name
        need(path.is_file() and not path.is_symlink(), 'regular candidate required: '+name)
        raw = path.read_bytes()
        compile(raw, str(path), 'exec')
        expected = ast.dump(ast.parse((package/'reference'/name).read_bytes()))
        need(ast.dump(ast.parse(raw)) == expected,
             'candidate implementation differs from passing package: '+name)
        snapshots[name] = raw
    # Include directly imported home Python helpers as context, never env/DB files.
    pending = list(snapshots)
    while pending:
        name = pending.pop()
        for node in ast.walk(ast.parse(snapshots[name])):
            modules = []
            if isinstance(node, ast.Import):
                modules = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                modules = [node.module]
            for module in modules:
                if '.' in module or not module.isidentifier():
                    continue
                dependency = module+'.py'
                if dependency in snapshots:
                    continue
                path = home/dependency
                if path.is_file() and not path.is_symlink():
                    need(len(snapshots) < 500, 'unexpectedly large helper graph')
                    snapshots[dependency] = path.read_bytes()
                    compile(snapshots[dependency], str(path), 'exec')
                    pending.append(dependency)
    staged = repo/'hilega-authorized-attempt-stage-xzqykzdz/adapter.py'
    need(staged.is_file() and not staged.is_symlink(), 'pinned fixture adapter source required')
    staged_raw = staged.read_bytes()
    need(digest(staged_raw) == '82c7606a4c4aad8b540b59db35766a736982dac18e9501f26179d9e8fe24b4a4',
         'fixture adapter source differs')
    folder = Path(tempfile.mkdtemp(prefix='hilega-three-cycle-freeze-', dir=repo))
    sources = folder/'home-sources'
    sources.mkdir()
    file_hashes = {}
    for name, raw in sorted(snapshots.items()):
        (sources/name).write_bytes(raw)
        file_hashes['home-sources/'+name] = digest(raw)
    (folder/'fixture-adapter.py').write_bytes(staged_raw)
    file_hashes['fixture-adapter.py'] = digest(staged_raw)
    (folder/'VM-VALIDATION.json').write_bytes(report_raw)
    file_hashes['VM-VALIDATION.json'] = digest(report_raw)
    for name in ('README.md', 'CONSOLIDATION_PLAN.md'):
        shutil.copyfile(package/name, folder/name)
        file_hashes[name] = digest((folder/name).read_bytes())
    # Refuse a successful seal if source inputs changed during the copy.
    need(report_path.read_bytes() == report_raw, 'validation report changed during freeze')
    need(staged.read_bytes() == staged_raw, 'fixture adapter changed during freeze')
    for name, raw in snapshots.items():
        need((home/name).read_bytes() == raw, 'home source changed during freeze: '+name)
    git = subprocess.run(['git', '-C', str(repo), 'rev-parse', 'HEAD'],
                         text=True, capture_output=True)
    checkpoint = dict(
        status='THREE_CYCLE_SOURCE_CHECKPOINT_FROZEN',
        assessed_at=datetime.now(timezone.utc).isoformat(),
        evidence_basis='EXISTING_VM_PASS_REPORT_AND_SOURCE_PARITY_CHECKS',
        reported_vm_cases_passed=120, pytest_reexecuted=False,
        verified_candidate_count=len(manifest['candidate_files']),
        copied_home_source_count=len(snapshots),
        scope='SYNTHETIC_FIXTURE_THREE_CYCLE_LIFECYCLE',
        git_head=git.stdout.strip() if git.returncode == 0 else None,
        standalone_runtime_bundle=False, repository_dependencies_still_required=True,
        fourth_entry_admission_implemented=False,
        production_execution_enabled=False, runtime_deployed=False,
        production_ready=False, files=file_hashes)
    raw = (json.dumps(checkpoint, indent=2)+'\n').encode()
    (folder/'CHECKPOINT.json').write_bytes(raw)
    print(json.dumps({
        'status': checkpoint['status'], 'checkpoint': str(folder),
        'checkpoint_sha256': digest(raw), 'reported_vm_cases_passed': 120,
        'verified_candidate_count': checkpoint['verified_candidate_count'],
        'copied_home_source_count': len(snapshots), 'pytest_reexecuted': False,
        'production_execution_enabled': False,
    }, indent=2))


if __name__ == '__main__':
    main()
