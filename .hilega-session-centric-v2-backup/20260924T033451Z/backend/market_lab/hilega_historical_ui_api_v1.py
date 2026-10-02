"""Read-only historical Hilega adapter for the existing Historical Replay page.

Never calls broker APIs, live coordinator, execution, or the existing replay worker.
Reads prior Phase 7D audit artifacts without mutating them.
"""
from __future__ import annotations

import json
import re
from datetime import date
from pathlib import Path
from fastapi import APIRouter, HTTPException, Query
from .hilega_milega_audit_report_v1 import build_audit_index
from .live_shadow_step_audit_v1 import ShadowStepAuditStoreV1

router = APIRouter(prefix='/api/live-shadow/hilega-historical', tags=['hilega-historical'])
ROOT = Path('data/historical-evidence')
NAME_RE = re.compile(r'^hilega-phase7d-(\d{4}-\d{2}-\d{2})(?:-[a-zA-Z0-9_-]+)?$')


def _candidate_dirs(root: Path = ROOT):
    if not root.is_dir():
        return []
    found = []
    for child in root.iterdir():
        if not child.is_dir() or child.is_symlink():
            continue
        match = NAME_RE.fullmatch(child.name)
        if not match:
            continue
        try:
            day = date.fromisoformat(match.group(1)).isoformat()
        except ValueError:
            continue
        if (child / 'step-audit.jsonl').is_file():
            found.append((day, child))
    return found


def list_available(root: Path = ROOT):
    sessions = []
    for day, directory in _candidate_dirs(root):
        mf = directory / 'source-manifest.json'
        manifest = _json_file(mf) if mf.is_file() else {}
        sessions.append({
            'session_date': day, 'capture_id': directory.name,
            'has_report': (directory / 'detailed-audit-report.json').is_file(),
            'has_manifest': mf.is_file(),
            'expiry': manifest.get('expiry'),
            'audit_path_present': True,
        })
    return sorted(sessions, key=lambda x:(x['session_date'], x['capture_id']), reverse=True)


def _json_file(path: Path):
    try:
        return json.loads(path.read_text(encoding='utf-8'))
    except (ValueError, OSError) as exc:
        raise HTTPException(422, f'Invalid historical artifact {path.name}: {type(exc).__name__}') from exc


def load_capture(capture_id: str, root: Path = ROOT):
    valid = {directory.name: (day, directory) for day, directory in _candidate_dirs(root)}
    if capture_id not in valid:
        raise HTTPException(404, 'Historical Hilega capture not found')
    day, directory = valid[capture_id]
    store = ShadowStepAuditStoreV1(directory / 'step-audit.jsonl')
    try:
        chain_ok, chain_issue = store.verify_chain()
        rows = store.read_all()
    except (ValueError, OSError, KeyError, TypeError) as exc:
        raise HTTPException(422, f'Historical audit unreadable: {type(exc).__name__}') from exc
    # Derived report is regenerated from the actual audit, preventing stale report files
    # from showing false candle/decision relationships.
    reports = build_audit_index(rows, mode='HISTORICAL_FUNCTIONAL_PARITY',
                                chain_ok=chain_ok, chain_issue=chain_issue)
    reports.sort(key=lambda x:x['checkpoint'])
    mf = directory/'source-manifest.json'
    manifest = _json_file(mf) if mf.is_file() else {}
    return {
        'session_date': day, 'capture_id': capture_id,
        'manifest': manifest, 'audit_chain_ok': chain_ok, 'audit_chain_issue': chain_issue,
        'reports': reports, 'report_count': len(reports),
        'observation_only': True, 'execution_enabled': False,
        'warning': ('Historical broker capture may differ from original live source data. '
                    'No original live parity is implied.'),
    }


@router.get('/sessions')
def sessions():
    return {'sessions': list_available()}


@router.get('/capture')
def capture(capture_id: str = Query(..., max_length=120)):
    return load_capture(capture_id)
