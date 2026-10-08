"""Isolated recovered replay registry. Never substitutes recorded live evidence."""
import copy
import json
from datetime import date
from pathlib import Path

ROOT = Path('data/recovery/october-2026/ui-replay')
LABEL = 'RECOVERED_HISTORICAL_REPLAY'

def load_hilega(day, strategy):
    date.fromisoformat(day)
    path = ROOT / 'hilega' / day / ('v1.json' if strategy == 'V1' else 'v2.json')
    if not path.exists():
        return None
    result = json.loads(path.read_text())
    if result.get('evidence_cohort') != LABEL or result.get('session_date') != day:
        raise ValueError('Invalid recovered replay provenance')
    return result

def hilega_sessions(existing):
    rows = {r['session_date']: copy.deepcopy(r) for r in existing}
    for path in (ROOT / 'hilega').glob('*/v2.json'):
        day = path.parent.name
        date.fromisoformat(day)
        row = rows.setdefault(day, {'session_date': day, 'source': LABEL,
            'source_id': 'recovered:' + day, 'status': 'COMPLETE',
            'evidence_level': 'STRATEGY', 'ce_available': False, 'expiry': None,
            'available_sources': []})
        row['available_sources'] = sorted(set(row.get('available_sources', []) + [LABEL]))
    return sorted(rows.values(), key=lambda r: r['session_date'], reverse=True)

def midpoint_manifest(existing):
    path = ROOT / 'midpoint' / 'manifest.json'
    if not path.exists():
        return existing
    recovered = json.loads(path.read_text())
    rows = {r['session_date']: r for r in existing.get('sessions', [])}
    rows.update({r['session_date']: r for r in recovered['sessions']})
    return {**existing, 'sessions': sorted(rows.values(), key=lambda r: r['session_date'], reverse=True)}

def midpoint_dir(day):
    date.fromisoformat(day)
    path = ROOT / 'midpoint' / day
    return path if (path / 'audit.jsonl').exists() else None
