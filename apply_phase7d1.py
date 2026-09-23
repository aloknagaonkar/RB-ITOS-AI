#!/usr/bin/env python3
"""Safely stage Phase 7D.1 against the user-supplied repository snapshot.

Default is dry-run. Does NOT restart processes, edit evidence, or use the broker.
"""
import argparse
import hashlib
import pathlib
import shutil
import subprocess
import sys
import zipfile
from datetime import datetime, timezone

BASELINE = {
    'backend/market_lab/gateways.py': '26b42e069a51a4cab45fbf61e84ee5e6020a70b1dda9f6a4485b9a0895a5c2af',
    'backend/market_lab/hilega_milega_functional_parity_replay_v1.py': '04a909b7815184df2837e38f4627d03953d4bea7e5bfafefcf1ee94c1a922fdb',
    'backend/market_lab/hilega_milega_phase7d_historical_capture_v1.py': '501bd5d6cac992bcefd67cee30f2bf50304cbb559938bdcff3a20e2d476670fe',
    'backend/market_lab/hilega_milega_live_shadow_v1.py': 'cdc6b459c1524b82fd08032badbb8e080f98afb12a6ffbb90bd2078b513e74c0',
    'tests/test_hilega_phase7d1_acquisition_v1.py': None,
    'tests/test_hilega_milega_functional_parity_replay_v1.py': 'f32ef72cb4bddb5085d39dc971c89981668cb33800fcc55cbbbd7d686f034dcb',
    'tests/test_hilega_milega_phase7c_pending_exit_v1.py': 'b3d2b0a29936f6b3cc2cae35f9810cf9b6be3d5df7540551c8aea2bd02d47d58',
}


def sha(data):
    return hashlib.sha256(data).hexdigest()


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--repo', type=pathlib.Path, default=pathlib.Path.home() / 'RB-ITOS-AI')
    p.add_argument('--patch', type=pathlib.Path, default=pathlib.Path(__file__).resolve().parent / 'hilega-phase7d1-patch.zip')
    p.add_argument('--apply', action='store_true', help='Apply ONLY if all original file hashes match the attached baseline')
    a = p.parse_args()
    root = a.repo.resolve()
    if not (root / 'backend/market_lab').is_dir():
        sys.exit(f'Invalid repository path: {root}')
    if not a.patch.is_file():
        sys.exit(f'Patch not found: {a.patch}')
    with zipfile.ZipFile(a.patch) as archive:
        missing = set(BASELINE) - set(archive.namelist())
        if missing:
            sys.exit(f'Patch missing expected paths: {sorted(missing)}')
        errors, changes = [], []
        for rel, baseline in BASELINE.items():
            path = root / rel
            current = sha(path.read_bytes()) if path.is_file() else None
            intended = sha(archive.read(rel))
            if current == intended:
                print('ALREADY_PATCHED ', rel)
            elif current != baseline:
                print('CONFLICT       ', rel)
                errors.append(rel)
            else:
                print('READY          ', rel)
                changes.append(rel)
        if errors:
            sys.exit('Refusing all changes: VM files differ from supplied reference. Inspect/reconcile manually; do not overwrite.')
        if not a.apply:
            print(f'\nDry-run only. {len(changes)} files ready. Use --apply after checking VM changes.')
            return
        if not changes:
            print('Everything already patched. No action.')
            return
        backup = root / '.phase7d1-backup' / datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
        for rel in changes:
            path = root / rel
            if path.exists():
                target = backup / rel
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(path, target)
        print('Backup existing files:', backup)
        for rel in changes:
            path = root / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(archive.read(rel))
            print('APPLIED        ', rel)
        print('No services restarted. Inspect git diff, run targeted tests, then perform offline capture.')


if __name__ == '__main__':
    main()
