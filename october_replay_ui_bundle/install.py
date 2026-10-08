"""Surgical installation; retains later VM changes and rolls back failed checks."""
import os
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

BUNDLE = Path(__file__).resolve().parent
ROOT = BUNDLE.parent

def once(text, old, new):
    if new in text:
        return text
    if text.count(old) != 1:
        raise RuntimeError('Source differs from expected patch anchor: ' + old[:90])
    return text.replace(old, new, 1)

def patches():
    api = ROOT / 'backend/market_lab/hilega_historical_ui_api_v1.py'
    text = api.read_text()
    text = once(text, '    is_v1 = strategy.strip().upper() == "V1"\n', '    is_v1 = strategy.strip().upper() == "V1"\n    from .recovered_replay_ui_v1 import load_hilega\n    recovered = load_hilega(day.isoformat(), "V1" if is_v1 else "V2")\n    if recovered is not None:\n        return recovered\n')
    text = once(text, '    return sorted(sessions, key=lambda x: x["session_date"], reverse=True)', '    from .recovered_replay_ui_v1 import hilega_sessions\n    return hilega_sessions(sorted(sessions, key=lambda x: x["session_date"], reverse=True))')
    api.write_text(text)
    mp = ROOT / 'backend/market_lab/midpoint_strategy/live_shadow_ui.py'
    text = mp.read_text()
    if 'def _base_manifest_recovered_adapter():' not in text:
        text = once(text, 'def _manifest():', 'def _base_manifest_recovered_adapter():')
        text = once(text, 'def _historical_session_dir(session_date: str) -> Path:', 'def _manifest():\n    from ..recovered_replay_ui_v1 import midpoint_manifest\n    return midpoint_manifest(_base_manifest_recovered_adapter())\n\n\ndef _historical_session_dir(session_date: str) -> Path:\n    from ..recovered_replay_ui_v1 import midpoint_dir\n    recovered = midpoint_dir(session_date)\n    if recovered is not None:\n        return recovered')
    mp.write_text(text)
    worker = ROOT / 'backend/market_lab/live_shadow_worker_v1.py'
    text = worker.read_text()
    start = text.index('def _resolve_hilega_option_expiry(')
    end = text.index('\ndef run(', start)
    text = text[:start] + 'def _resolve_hilega_option_expiry(sources, *, session_date: date, configured_raw: str):\n    from .hilega_expiry_rollover_v1 import resolve_expiry\n    return resolve_expiry(sources, session_date=session_date, configured_raw=configured_raw)\n\n' + text[end:]
    if '# AUTO_EXPIRY_DAILY_GUARD' not in text:
        anchor = '                    if now.second>=30:'
        if text.count(anchor) != 2:
            raise RuntimeError('Expected both Hilega daily processing loops; refusing partial expiry patch')
        guard = '''                    # AUTO_EXPIRY_DAILY_GUARD — independent of evidence recording.
                    if getattr(coord, '_expiry_session_date', None) != now.date():
                        option_expiry, option_expiry_source = _resolve_hilega_option_expiry(
                            sources, session_date=now.date(), configured_raw=expiry_raw)
                        coord.option_expiry = option_expiry
                        coord._expiry_session_date = now.date()
                    if now.second>=30:'''
        text = text.replace(anchor, guard)
    worker.write_text(text)
    legacy_test = ROOT / 'tests/test_hilega_option_expiry_resolution_v1.py'
    if legacy_test.exists():
        text = legacy_test.read_text()
        text = once(text, 'def test_configured_expiry_is_exact_override():', 'def test_configured_expiry_is_exact_override(monkeypatch):\n    monkeypatch.setenv("HILEGA_OPTION_EXPIRY_MODE", "MANUAL")')
        text = once(text, 'assert source_name == "CONFIGURED_ENV"', 'assert source_name == "EXPLICIT_MANUAL_EXPIRY"')
        legacy_test.write_text(text)
    frontend = ROOT / 'frontend/src/midpointStrategyShadow.tsx'
    text = frontend.read_text()
    text = once(text, '<b>HISTORICAL REPLAY</b>', '<b>{selectedSession?.block===\'RECOVERED_HISTORICAL_REPLAY\'?\'RECOVERED HISTORICAL REPLAY\':\'HISTORICAL REPLAY\'}</b>')
    frontend.write_text(text)
    hilega_frontend = ROOT / 'frontend/src/hilegaHistoricalReplay.tsx'
    text = hilega_frontend.read_text()
    text = once(text, 'if(dr.ok){', "if(dr.ok && body.source!=='RECOVERED_HISTORICAL_REPLAY'){")
    old = '<HilegaDirectionalReplayTrades sessionDate={selectedDate} />'
    new = '''{data?.source==='RECOVERED_HISTORICAL_REPLAY' ? <section className="panel"><h4>Recovered NIFTY trades · no option fills</h4><div style={{overflowX:'auto'}}><table><thead><tr><th>Direction</th><th>Signal candle</th><th>Decision</th><th>Entry time</th><th>Entry NIFTY</th><th>Exit candle</th><th>Exit NIFTY</th><th>Points</th><th>Canonical points</th></tr></thead><tbody>{((data as any).recovered_trades??[]).map((r:any)=><tr key={r.trade_id}><td>{r.direction}</td><td>{shortTime(r.entry_timestamp)}</td><td>{strategyVersion==='V1'?'ENTRY':r.candidate_decision}</td><td>{strategyVersion==='V1'?shortTime(r.entry_timestamp):r.candidate_entry_timestamp?shortTime(r.candidate_entry_timestamp):'—'}</td><td>{strategyVersion==='V1'?Number(r.entry_price).toFixed(2):r.candidate_entry_price==null?'—':Number(r.candidate_entry_price).toFixed(2)}</td><td>{shortTime(r.exit_timestamp)}</td><td>{Number(r.exit_price).toFixed(2)}</td><td>{strategyVersion==='V1'?Number(r.canonical_points).toFixed(2):r.candidate_points==null?'Not entered':Number(r.candidate_points).toFixed(2)}</td><td>{Number(r.canonical_points).toFixed(2)}</td></tr>)}</tbody></table></div><p>Denied V2 rows show the original canonical exit for comparison, not a V2 exit. Times are candle labels; no fees or slippage included.</p></section> : <HilegaDirectionalReplayTrades sessionDate={selectedDate} />}'''
    text = once(text, old, new)
    hilega_frontend.write_text(text)

def main():
    if not (ROOT / 'backend/market_lab/hilega_historical_ui_api_v1.py').is_file():
        raise SystemExit('STOP: extract this bundle inside RB-ITOS-AI and run it from that repository.')
    patch_paths = [ROOT / p for p in ['backend/market_lab/hilega_historical_ui_api_v1.py', 'backend/market_lab/midpoint_strategy/live_shadow_ui.py', 'backend/market_lab/live_shadow_worker_v1.py', 'frontend/src/midpointStrategyShadow.tsx', 'frontend/src/hilegaHistoricalReplay.tsx']]
    legacy_test = ROOT / 'tests/test_hilega_option_expiry_resolution_v1.py'
    if legacy_test.exists():
        patch_paths.append(legacy_test)
    new_paths = [ROOT / p.relative_to(BUNDLE / 'files') for p in (BUNDLE / 'files').rglob('*') if p.is_file()]
    paths = patch_paths + new_paths
    backup = ROOT / 'data/backups' / ('october-replay-ui-' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ'))
    backup.mkdir(parents=True)
    previous = {}
    for path in paths:
        previous[path] = path.exists()
        if path.exists():
            saved = backup / path.relative_to(ROOT); saved.parent.mkdir(parents=True, exist_ok=True); shutil.copy2(path, saved)
    try:
        for source in (BUNDLE / 'files').rglob('*'):
            if source.is_file():
                dest = ROOT / source.relative_to(BUNDLE / 'files'); dest.parent.mkdir(parents=True, exist_ok=True); shutil.copy2(source, dest)
        patches()
        env = {**os.environ, 'PYTHONPATH': str(ROOT / 'backend') + ':' + str(ROOT)}
        regression = ['tests/test_october_recovered_replay_ui.py']
        for name in ['test_hilega_option_expiry_resolution_v1.py', 'test_hilega_wma_gap_historical_v1.py', 'test_hilega_historical_ui_api_v1.py', 'test_hilega_upstox_sandbox_execution_v1.py', 'test_shadow_session_recovery.py', 'test_midpoint_health_audit_inspect.py']:
            if (ROOT / 'tests' / name).exists():
                regression.append('tests/' + name)
        commands = [[sys.executable, '-m', 'pytest', '-q', *regression],
            [sys.executable, '-m', 'py_compile', *[str(p) for p in patch_paths if p.suffix == '.py'], 'scripts/publish_october_recovered_replay.py'],
            ['npm', '--prefix', 'frontend', 'run', 'build']]
        if (ROOT / '.git').exists():
            commands.append(['git', 'diff', '--check'])
        for command in commands:
            print('Running:', ' '.join(command), flush=True)
            subprocess.run(command, cwd=ROOT, env=env, check=True)
    except Exception:
        for path, existed in previous.items():
            if existed:
                shutil.copy2(backup / path.relative_to(ROOT), path)
            elif path.exists():
                path.unlink()
        print('STOP: source restored; frontend dist may need rebuilding.', file=sys.stderr)
        raise
    print('PASS: isolated recovered replay routing and automatic expiry guard installed.')
    print('No replay publication, broker call, order, live audit or frozen evidence changed.')
    print('Backup:', backup)

if __name__ == '__main__':
    main()
