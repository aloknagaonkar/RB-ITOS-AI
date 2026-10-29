import hashlib
import importlib.util
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

folder=Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location('recovery',folder/'recover-supervision-v2.py')
r=importlib.util.module_from_spec(spec);spec.loader.exec_module(r)

class RecoveryGuards(unittest.TestCase):
    def text(self,root):
        return '[Unit]\nDescription=Hilega unit parser check\n[Service]\nType=exec\nWorkingDirectory="'+str(root)+'"\nExecStart=/usr/bin/true\nRestart=on-failure\nRestartPreventExitStatus=78\n'
    def fixed(self,root,text):
        return r.corrected_unit(text,root,root,'api',hashlib.sha256(self.text(root).encode()).hexdigest())
    def test_exact_directory_correction(self):
        root=Path('/tmp/project'); original=self.text(root)
        self.assertEqual(self.fixed(root,original),original.replace('WorkingDirectory="/tmp/project"','WorkingDirectory=/tmp/project'))
    def test_already_corrected_content_accepted(self):
        root=Path('/tmp/project'); corrected=self.fixed(root,self.text(root))
        self.assertEqual(self.fixed(root,corrected),corrected)
    def test_other_unit_changes_rejected(self):
        root=Path('/tmp/project')
        with self.assertRaisesRegex(RuntimeError,'OTHER_UNIT_CONTENT_CHANGED'):
            self.fixed(root,self.text(root).replace('/usr/bin/true','/usr/bin/false'))
    def test_duplicate_directory_rejected(self):
        root=Path('/tmp/project')
        with self.assertRaisesRegex(RuntimeError,'DIRECTORY_SETTING_UNEXPECTED'):
            self.fixed(root,self.text(root)+'WorkingDirectory="/tmp/project"\n')
    def test_missing_directory_rejected(self):
        root=Path('/tmp/project')
        with self.assertRaisesRegex(RuntimeError,'DIRECTORY_SETTING_UNEXPECTED'):
            self.fixed(root,self.text(root).replace('WorkingDirectory="/tmp/project"\n',''))
    def test_only_detached_pair_accepted(self):
        r.validate_inventory([dict(role='api',pid=1),dict(role='worker',pid=2)])
    def test_existing_source_blocks_recovery(self):
        with self.assertRaisesRegex(RuntimeError,'EXPECTED_ONLY_DETACHED'):
            r.validate_inventory([dict(role='api',pid=1),dict(role='worker',pid=2),dict(role='production-source-worker',pid=3)])
    def test_duplicate_pid_rejected(self):
        with self.assertRaisesRegex(RuntimeError,'DUPLICATE_PROCESS_ID'):
            r.validate_inventory([dict(role='api',pid=1),dict(role='worker',pid=1)])
    def test_atomic_repair_preserves_private_permissions(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'unit';p.write_text('old')
            r.atomic_text(p,'new')
            self.assertEqual(p.read_text(),'new');self.assertEqual(p.stat().st_mode & 0o777,0o600)
    def test_parser_reproduces_original_failure(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);p=root/'hilega-parser.service';p.write_text(self.text(root))
            result=subprocess.run(['systemd-analyze','verify',str(p)],capture_output=True,text=True)
            self.assertNotEqual(result.returncode,0)
            self.assertIn('path is not absolute',result.stderr)
    def test_parser_accepts_corrected_unit(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);p=root/'hilega-parser.service';p.write_text(self.fixed(root,self.text(root)))
            result=subprocess.run(['systemd-analyze','verify',str(p)],capture_output=True,text=True)
            self.assertEqual(result.returncode,0,result.stderr)
    def test_systemd_failure_stops_command(self):
        with patch.object(r.subprocess,'run',return_value=type('Result',(),dict(returncode=1,stdout=''))()):
            with self.assertRaisesRegex(RuntimeError,'COMMAND_FAILED_systemctl'):r.run(['systemctl'])

if __name__=='__main__':unittest.main()
