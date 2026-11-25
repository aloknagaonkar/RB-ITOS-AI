from contextlib import redirect_stdout
import importlib.util
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

spec=importlib.util.spec_from_file_location('ui_install',Path(__file__).parents[1]/'install.py')
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)


class InstallTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.repo=self.root/'repo';self.stage=self.root/'stage'
        self.repo.mkdir();self.stage.mkdir()
        self.source='backend/market_lab/ui.py'
        self.old={self.source:b'old source','frontend/dist/index.html':b'old index',
                  'frontend/dist/assets/old-hash.js':b'old tab asset','.env':b'unchanged settings'}
        self.new={self.source:b'new source','frontend/dist/index.html':b'new index',
                  'frontend/dist/assets/new-hash.js':b'new asset'}
        for rel,raw in self.old.items():
            p=self.repo/rel;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(raw)
        for rel,raw in self.new.items():
            p=self.stage/rel;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(raw)
        self.manifest=dict(strategy_version='same-policy',files={self.source:dict(
            before=m.digest(self.old[self.source]),after=m.digest(self.new[self.source]))},
            built_asset_sha256={'index.html':m.digest(b'new index'),'assets/new-hash.js':m.digest(b'new asset')})
        self.prepared=dict(status='UI_POLICY_FIX_PREPARED_NOT_INSTALLED',repo=str(self.repo),stage=str(self.stage),
            strategy_version='same-policy',files=self.manifest['files'],built_asset_sha256=self.manifest['built_asset_sha256'])
        (self.stage/'preparation.json').write_text(json.dumps(self.prepared))
        self.service_states={name:dict(ActiveState='active',SubState='running',MainPID=str(i+100),
            WorkingDirectory=str(self.repo),NRestarts='0') for i,name in enumerate(m.RESTART+m.PROTECTED)}
        self.calls=[]

    def control(self,*args):
        self.calls.append(args)
        if args[0] in ('start','stop'):
            for name in args[1:]:
                state=self.service_states[name]
                state['ActiveState']='active' if args[0]=='start' else 'inactive'
                state['SubState']='running' if args[0]=='start' else 'dead'
        return None

    def transaction(self,verify=None):
        with patch.object(m,'unit',side_effect=lambda n:dict(self.service_states[n])),\
             patch.object(m,'systemctl',side_effect=self.control),\
             patch.object(m,'status',return_value={}),\
             patch.object(m,'reference_arguments',return_value=['--watch']),\
             patch.object(m,'package_check',return_value={}),\
             patch.object(m,'reference_check',return_value={}),\
             patch.object(m,'verify_api',side_effect=verify or (lambda *a:dict(browser_display_verified=False))),\
             redirect_stdout(io.StringIO()):
            m.install(self.repo,self.stage,'http://127.0.0.1:8123',self.manifest)

    def receipt(self):
        p=next((self.repo/'data/deployments').glob('*/receipt.json'))
        return json.loads(p.read_text())

    def test_prepared_build_exact_match(self):
        self.assertEqual(len(m.verify_prepared(self.repo,self.stage,self.manifest)),3)

    def test_prepared_asset_tamper_rejected(self):
        (self.stage/'frontend/dist/index.html').write_bytes(b'changed')
        with self.assertRaisesRegex(ValueError,'PREPARED_FILE_CHANGED'):m.verify_prepared(self.repo,self.stage,self.manifest)

    def test_prepared_report_tamper_rejected(self):
        self.prepared['files']={};(self.stage/'preparation.json').write_text(json.dumps(self.prepared))
        with self.assertRaisesRegex(ValueError,'PREPARED_BUILD_DIFFERS'):m.verify_prepared(self.repo,self.stage,self.manifest)

    def test_extra_asset_rejected(self):
        (self.stage/'frontend/dist/unreviewed.js').write_bytes(b'x')
        with self.assertRaisesRegex(ValueError,'UNEXPECTED_PREPARED_ASSET_SET'):m.verify_prepared(self.repo,self.stage,self.manifest)

    def test_source_lease_rejects_newer_vm_edit(self):
        (self.repo/self.source).write_bytes(b'another deployment')
        with self.assertRaisesRegex(ValueError,'SOURCE_CHANGED'):self.transaction()
        self.assertEqual(self.calls,[])

    def test_success_preserves_old_assets_and_protected_workers(self):
        self.transaction()
        for rel,raw in self.new.items():self.assertEqual((self.repo/rel).read_bytes(),raw)
        self.assertEqual((self.repo/'frontend/dist/assets/old-hash.js').read_bytes(),b'old tab asset')
        self.assertEqual((self.repo/'.env').read_bytes(),self.old['.env'])
        self.assertEqual(self.receipt()['status'],'UI_POLICY_FIX_DEPLOYED_API_VERIFIED')
        for call in self.calls:self.assertTrue(set(call[1:])<=set(m.RESTART))

    def test_failed_verification_restores_sources_and_index(self):
        def fail(*args):raise ValueError('simulated verification failure')
        with self.assertRaisesRegex(ValueError,'simulated'):self.transaction(fail)
        for rel,raw in self.old.items():self.assertEqual((self.repo/rel).read_bytes(),raw)
        self.assertFalse((self.repo/'frontend/dist/assets/new-hash.js').exists())
        self.assertEqual(self.receipt()['status'],'ROLLED_BACK_AFTER_INSTALL_FAILURE')
        self.assertTrue(all(self.service_states[n]['ActiveState']=='active' for n in m.RESTART))

    def test_rollback_does_not_overwrite_concurrent_change(self):
        def fail(*args):
            (self.repo/self.source).write_bytes(b'concurrent edit')
            raise ValueError('verify failed')
        with self.assertRaises(ValueError):self.transaction(fail)
        self.assertEqual((self.repo/self.source).read_bytes(),b'concurrent edit')
        self.assertEqual(self.receipt()['status'],'ROLLBACK_REQUIRES_ATTENTION')

    def test_atomic_write_refuses_symlink(self):
        real=self.root/'real';real.write_bytes(b'original');link=self.root/'link';link.symlink_to(real)
        with self.assertRaisesRegex(ValueError,'SYMLINK'):m.atomic_file(link,b'changed')
        self.assertEqual(real.read_bytes(),b'original')

    def test_partial_install_failure_is_rolled_back(self):
        original=m.atomic_file;seen=[]
        def fail_once(path,content,mode=0o644):
            seen.append(path)
            if len(seen)==2:raise OSError('simulated disk failure')
            return original(path,content,mode)
        with patch.object(m,'atomic_file',side_effect=fail_once):
            with self.assertRaises(OSError):self.transaction()
        for rel,raw in self.old.items():self.assertEqual((self.repo/rel).read_bytes(),raw)
        self.assertEqual(self.receipt()['status'],'ROLLED_BACK_AFTER_INSTALL_FAILURE')


if __name__=='__main__':unittest.main()
