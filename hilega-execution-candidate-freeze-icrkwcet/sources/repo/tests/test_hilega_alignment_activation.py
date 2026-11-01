import importlib.util, tempfile, unittest
from pathlib import Path
from unittest.mock import patch, Mock
ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('alignment_activation',ROOT/'hilega_alignment_dual_exit_live_bundle/activate.py')
module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)

class ActivationTests(unittest.TestCase):
    def test_only_strategy_changes_and_arm_is_local(self):
        import os
        original=os.getcwd()
        try:
            with tempfile.TemporaryDirectory() as td:
                root=Path(td);env=root/'.env'
                env.write_text('KEEP_THIS=original\nLIVE_SHADOW_STRATEGY=HILEGA_WMA_GAP_V2_LIVE_SHADOW\nHILEGA_UPSTOX_SANDBOX_LOTS=1\n')
                expected={'strategy_id':module.STRATEGY_ID,'session_date':'2026-10-12','armed':True}
                arm=Mock(return_value=expected)
                with patch.object(module,'ROOT',root),patch.object(module,'CONTROL',root/'control'),patch.object(module,'JOURNAL',root/'journal'),patch.dict(os.environ,{'LIVE_SHADOW_STRATEGY':''}),patch.object(module.SandboxConfig,'from_env',return_value=Mock(spec=["assert_ready"])),patch.object(module,'validate_warmup'),patch.object(module,'ensure_clear'),patch.object(module,'arm',arm):
                    module.select('2026-10-12')
                self.assertIn('KEEP_THIS=original\n',env.read_text())
                self.assertIn('HILEGA_UPSTOX_SANDBOX_LOTS=1\n',env.read_text())
                self.assertIn('LIVE_SHADOW_STRATEGY='+module.STRATEGY_ID,env.read_text())
                arm.assert_called_once()
        finally:os.chdir(original)

    def test_failed_arm_restores_env(self):
        import os
        original=os.getcwd()
        try:
            with tempfile.TemporaryDirectory() as td:
                root=Path(td);env=root/'.env';before=b'KEEP_THIS=original\n';env.write_bytes(before)
                with patch.object(module,'ROOT',root),patch.object(module,'CONTROL',root/'control'),patch.object(module,'JOURNAL',root/'journal'),patch.dict(os.environ,{'LIVE_SHADOW_STRATEGY':''}),patch.object(module.SandboxConfig,'from_env',return_value=Mock(spec=["assert_ready"])),patch.object(module,'validate_warmup'),patch.object(module,'ensure_clear'),patch.object(module,'arm',side_effect=ValueError('blocked')):
                    with self.assertRaises(ValueError):module.select('2026-10-12')
                self.assertEqual(env.read_bytes(),before)
        finally:os.chdir(original)
