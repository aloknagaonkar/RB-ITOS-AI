import ast
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

PACKAGE=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(PACKAGE))
import manage
import companion_bindings as companion

class InstallTests(unittest.TestCase):
    def test_source_patch_preserves_old_components_and_future_import(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            api=root/'backend/market_lab/api.py';api.parent.mkdir(parents=True)
            source='"""API"""\nfrom __future__ import annotations\ndef create_app():\n    app.include_router(hilega_historical_router)\n    return app\n'
            api.write_text(source)
            for name in ('HilegaHistoricalReplay','HilegaMilegaShadow'):
                p=root/'frontend/src'/(name[0].lower()+name[1:]+'.tsx');p.parent.mkdir(parents=True,exist_ok=True)
                p.write_text("import {useState} from 'react'\nexport default function "+name+"(){return <p>legacy unchanged</p>}\n")
            updates=manage.patches(root)
            result=updates['backend/market_lab/api.py'].decode();ast.parse(result)
            self.assertIn('app.include_router(hilega_rsi_two_route_router)',result)
            self.assertEqual(api.read_text(),source)
            self.assertLess(result.index('from __future__'),result.index('from .hilega_rsi'))
            for rel in ('frontend/src/hilegaHistoricalReplay.tsx','frontend/src/hilegaMilegaShadow.tsx'):
                self.assertIn('legacy unchanged',updates[rel].decode())
                self.assertIn("useState<'legacy' | 'rsi'>('legacy')",updates[rel].decode())
            api.write_text(source.replace('hilega_historical_router','changed_router'))
            with self.assertRaisesRegex(ValueError,'ANCHOR_CHANGED'):manage.patches(root)

    def test_companion_pins_only_explicit_backend_changes(self):
        manifest=dict(model='HILEGA_OPERATIONAL_LIFECYCLE_PACKAGE_V1',order_actions_available=False,
                      production_execution_enabled=False,runtime={'backend/old.py':'unchanged'})
        raw=json.dumps(manifest).encode();cli=("EXPECTED_MANIFEST = '"+companion.digest(raw)+"'\n").encode()
        original={str(companion.PACKAGE/'manifest.json'):raw,str(companion.PACKAGE/'cli.py'):cli,
            str(companion.SERVICE):("CLI_SHA = '"+companion.digest(cli)+"'\n").encode()}
        result=companion.rebind(original,{'backend/new.py':b'new','frontend/a.tsx':b'ignored'})
        updated=json.loads(result['files'][str(companion.PACKAGE/'manifest.json')])
        self.assertEqual(updated['runtime'],{'backend/old.py':'unchanged','backend/new.py':companion.digest(b'new')})
        self.assertFalse(updated['production_execution_enabled']);self.assertFalse(updated['order_actions_available'])

    def test_rollback_guard_then_restores_only_owned_paths(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);backup=root/'backup';backup.mkdir()
            path=root/'backend/change.py';path.parent.mkdir(parents=True);path.write_bytes(b'new')
            original=backup/'original/backend/change.py';original.parent.mkdir(parents=True);original.write_bytes(b'old')
            journal=root/'data/journal.json';journal.parent.mkdir();journal.write_bytes(b'keep')
            r=dict(repo=str(root),unit_path=str(root/'new.service'),files={'backend/change.py':dict(before=manage.sha(b'old'),after=manage.sha(b'new'))})
            path.write_bytes(b'user change')
            with self.assertRaisesRegex(ValueError,'ROLLBACK_FILE_CHANGED'):manage.rollback_files(backup,r)
            self.assertEqual(path.read_bytes(),b'user change')
            path.write_bytes(b'new')
            with patch.object(manage,'ctl') as ctl:manage.rollback_files(backup,r)
            self.assertEqual(path.read_bytes(),b'old');self.assertEqual(journal.read_bytes(),b'keep')
            self.assertEqual(ctl.call_args.args,('restart',manage.API,manage.REFERENCE))

    def test_apply_source_lease_refuses_before_writes(self):
        from types import SimpleNamespace
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);repo=root/'repo';repo.mkdir();stage=root/'stage';stage.mkdir()
            package=root/'package';package.mkdir();(package/'package-manifest.json').write_text('{}')
            (repo/'source.py').write_bytes(b'user changed');(stage/'source.py').write_bytes(b'candidate')
            receipt=dict(repo=str(repo),stage=str(stage),package_sha256=manage.sha(b'{}'),
                files={'source.py':dict(before=manage.sha(b'expected old'),after=manage.sha(b'candidate'))},assets={})
            (stage/'prepared.json').write_text(json.dumps(receipt))
            args=SimpleNamespace(repo=repo,stage=stage)
            with patch.object(manage,'HERE',package), patch.object(manage,'assert_package'), patch.object(manage,'protected',return_value={}), patch.object(manage,'unit',return_value={'ActiveState':'inactive'}), patch.object(manage.Path,'home',return_value=root):
                with self.assertRaisesRegex(ValueError,'SOURCE_LEASE_CHANGED'):manage.apply(args)
            self.assertEqual((repo/'source.py').read_bytes(),b'user changed')
            self.assertFalse((repo/'data').exists())

    def test_install_never_applies_when_preparation_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(sys,'argv',['manage.py','--install','--repo',tmp]), patch.object(manage,'prepare',side_effect=ValueError('BUILD_FAILED')), patch.object(manage,'apply') as apply:
                with self.assertRaisesRegex(ValueError,'BUILD_FAILED'):manage.main()
                apply.assert_not_called()

    def test_no_order_transports_or_existing_worker_updates(self):
        module_root=PACKAGE/'files/backend/market_lab/hilega_rsi_two_route_v1'
        for p in module_root.glob('*.py'):
            tree=ast.parse(p.read_text())
            imports=[n.module or '' for n in ast.walk(tree) if isinstance(n,ast.ImportFrom)]
            self.assertFalse(any('order' in n or 'sandbox' in n for n in imports),p.name)
        self.assertFalse((PACKAGE/'files/backend/market_lab/live_shadow_worker_v1.py').exists())
        self.assertIn('SIMULATION_ONLY',(module_root/'api.py').read_text())

if __name__=='__main__':unittest.main()
