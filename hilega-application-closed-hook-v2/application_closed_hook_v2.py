"""Stage an exact-hash application hook. Never execute main or change services."""
import ast
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import subprocess
import tempfile

EXPECTED = '9fd8bc6b22af63229f59743722cfb156b12feb0ca279bc2117a103d02670de98'
SCRIPT = 'hilega_production_simulator_bridge.py'
HOOK = '''def preparation_tick(bridge, path, *, test_fixture_consumer=None):
    """Preparation followed by a closed boundary; Python-only fixture injection."""
    result = bridge.run_source_once(path)
    from market_lab.hilega_closed_execution_boundary_v1 import worker_tick
    return dict(result, execution_handoff=worker_tick(fixture_consumer=test_fixture_consumer))
'''


def need(ok, reason):
    if not ok:
        raise ValueError(reason)


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def make_candidate(raw):
    need(digest(raw) == EXPECTED, 'APPLICATION_WORKER_HASH_CHANGED')
    text = raw.decode()
    tree = ast.parse(text)
    need(not any(isinstance(n, ast.FunctionDef) and n.name == 'preparation_tick'
                 for n in tree.body), 'APPLICATION_HOOK_ALREADY_PRESENT')
    main = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'main')
    matches = [n for n in ast.walk(main) if isinstance(n, ast.Assign)
               and any(isinstance(t, ast.Name) and t.id == 'result' for t in n.targets)]
    need(len(matches) == 1, 'EXACT_WORKER_RESULT_ASSIGNMENT_REQUIRED')
    node = matches[0]
    indent = ' '*node.col_offset
    replacement = (indent+'result = (\n'+indent+'    preparation_tick(bridge, a.source)\n'
                   +indent+'    if preparation_only else bridge.run_source_once(a.source)\n'
                   +indent+')\n')
    lines = text.splitlines(keepends=True)
    lines[node.lineno-1:node.end_lineno] = [replacement]
    lines[main.lineno-1:main.lineno-1] = [HOOK+'\n']
    result = ''.join(lines).encode()
    compile(result, '<closed-application-candidate>', 'exec')
    return result


def safe_unit(scope, unit, properties):
    scripts = []
    cwd = properties.get('WorkingDirectory', '')
    for token in re.findall(r'[A-Za-z0-9_./+\-]+\.py\b', properties.get('ExecStart', '')):
        path = Path(token)
        if not path.is_absolute():
            if not cwd.startswith('/'):
                continue
            path = Path(cwd)/path
        if path.is_file() and not path.is_symlink():
            scripts.append(str(path.resolve()))
    return dict(scope=scope, unit=unit, active=properties.get('ActiveState'),
                sub_state=properties.get('SubState'), enabled=properties.get('UnitFileState'),
                fragment_path=properties.get('FragmentPath'), working_directory=cwd,
                script_paths=sorted(set(scripts)))


def inventory():
    services, limitations = [], []
    units = ('hilega-production-source-worker.service', 'hilega-worker.service',
             'hilega-lifecycle-reference.service', 'hilega-api.service',
             'hilega-observation-analytics.service', 'hilega-observation-readiness.service')
    for scope, prefix in [('user', ['systemctl', '--user']), ('system', ['systemctl'])]:
        for unit in units:
            try:
                value = subprocess.run(prefix+['show', unit, '--no-pager',
                    '--property=LoadState,ActiveState,SubState,UnitFileState,FragmentPath,WorkingDirectory,ExecStart'],
                    text=True, capture_output=True, timeout=3)
                data = dict(line.split('=', 1) for line in value.stdout.splitlines() if '=' in line)
                if value.returncode or data.get('LoadState') == 'not-found':
                    continue
                services.append(safe_unit(scope, unit, data))
            except (OSError, subprocess.TimeoutExpired):
                limitations.append(dict(scope=scope, unit=unit, reason='QUERY_UNAVAILABLE'))
                break
    return services, limitations


def stage(repo):
    repo = Path(repo).resolve()
    source = repo/'scripts'/SCRIPT
    need(source.is_file() and not source.is_symlink(), 'REGULAR_INSTALLED_WORKER_REQUIRED')
    raw = source.read_bytes()
    candidate = make_candidate(raw)
    component = Path(__file__).with_name('fixture_closed_worker.py')
    need(component.is_file() and not component.is_symlink(), 'REGULAR_CLOSED_BOUNDARY_REQUIRED')
    boundary = component.read_bytes()
    compile(boundary, str(component), 'exec')
    services, limitations = inventory()
    folder = Path(tempfile.mkdtemp(prefix='hilega-application-closed-hook-stage-', dir=repo))
    target = folder/'scripts'/SCRIPT
    target.parent.mkdir()
    target.write_bytes(candidate)
    backend = folder/'backend/market_lab/hilega_closed_execution_boundary_v1.py'
    backend.parent.mkdir(parents=True)
    backend.write_bytes(boundary)
    need(source.read_bytes() == raw, 'INSTALLED_WORKER_CHANGED_DURING_STAGING')
    matches = [u for u in services if str(source) in u['script_paths']]
    report = dict(status='CLOSED_APPLICATION_HOOK_STAGED',
                  assessed_at=datetime.now(timezone.utc).isoformat(), stage=str(folder),
                  original_path=str(source), original_sha256=digest(raw),
                  candidate_path=str(target), candidate_sha256=digest(candidate),
                  boundary_path=str(backend), boundary_sha256=digest(boundary),
                  related_services=services, source_worker_units=matches,
                  service_mapping_confirmed=bool(matches), inventory_limitations=limitations,
                  installed_sources_modified=False, candidate_main_executed=False,
                  application_databases_opened=False, raw_arguments_exported=False,
                  environment_files_opened=False, service_control_commands_issued=False,
                  production_execution_enabled=False, runtime_deployed=False, production_ready=False)
    (folder/'DISCOVERY.json').write_text(json.dumps(report, indent=2)+'\n')
    return report
