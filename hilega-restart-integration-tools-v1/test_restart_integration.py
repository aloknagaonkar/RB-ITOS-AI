import importlib.util
from pathlib import Path
import subprocess
import os
import tempfile
import unittest

folder=Path(__file__).resolve().parent

def load(name,file):
 s=importlib.util.spec_from_file_location(name,folder/file)
 m=importlib.util.module_from_spec(s);s.loader.exec_module(m);return m
p=load('integrator','integrate-restart.py');h=load('helper','hilega_supervised_control.py')

class Tests(unittest.TestCase):
 def test_all_shell_changes_parse_and_keep_observer_hooks(self):
  for name,(anchor,action) in p.ANCHORS.items():
   text='#!/bin/bash\nset -euo pipefail\n'+anchor+'\n# observer hook retained\necho observer\n'
   result=p.patch_shell(name,text)
   self.assertIn('echo observer',result)
   self.assertIn('supervision_rc',result)
   with tempfile.TemporaryDirectory() as d:
    f=Path(d)/name;f.write_text(result)
    self.assertEqual(subprocess.run(['bash','-n',str(f)]).returncode,0)
 def exercise_shell_branch(self, mode_code):
  with tempfile.TemporaryDirectory() as d:
   root=Path(d);(root/'scripts').mkdir()
   (root/'scripts/hilega_supervised_control.py').write_text('import sys\nif sys.argv[1]=="mode":raise SystemExit('+str(mode_code)+')\nprint("SUPERVISED_START")\n')
   text='#!/bin/bash\nset -euo pipefail\nROOT="'+str(root)+'"\nPYTHON="'+os.sys.executable+'"\nstart_service() { echo "LEGACY_$1"; }\n'+p.ANCHORS['start.sh'][0]+'\n'
   f=root/'start.sh';f.write_text(p.patch_shell('start.sh',text))
   return subprocess.run(['bash',str(f)],capture_output=True,text=True)
 def test_shell_supervision_branch_never_calls_legacy(self):
  result=self.exercise_shell_branch(0)
  self.assertEqual(result.returncode,0);self.assertIn('SUPERVISED_START',result.stdout);self.assertNotIn('LEGACY_',result.stdout)
 def test_shell_no_units_branch_preserves_legacy(self):
  result=self.exercise_shell_branch(10)
  self.assertEqual(result.returncode,0);self.assertIn('LEGACY_api',result.stdout);self.assertIn('LEGACY_worker',result.stdout)
 def test_shell_failure_never_falls_back(self):
  result=self.exercise_shell_branch(78)
  self.assertEqual(result.returncode,78);self.assertNotIn('LEGACY_',result.stdout)
 def test_restart_anchors_working_directory(self):
  text='#!/bin/bash\n"$ROOT/scripts/stop.sh"\n"$ROOT/scripts/start.sh"\n'
  self.assertIn('cd "$ROOT"\n\n"$ROOT/scripts/stop.sh"',p.patch_shell('restart.sh',text))
 def test_missing_anchor_rejected(self):
  with self.assertRaisesRegex(ValueError,'ANCHOR_CHANGED'):p.patch_shell('start.sh','echo unrelated')
 def test_duplicate_anchor_rejected(self):
  with self.assertRaises(ValueError):p.patch_shell('stop.sh',p.ANCHORS['stop.sh'][0]*2)
 def test_reapply_rejected(self):
  text=p.patch_shell('start.sh',p.ANCHORS['start.sh'][0])
  with self.assertRaisesRegex(ValueError,'ALREADY_INTEGRATED'):p.patch_shell('start.sh',text)
 def test_no_units_allows_legacy(self):
  with tempfile.TemporaryDirectory() as d:self.assertFalse(h.service_mode(Path(d),Path(d)))
 def test_partial_units_blocks_legacy(self):
  with tempfile.TemporaryDirectory() as d:
   home=Path(d);u=home/'.config/systemd/user';u.mkdir(parents=True)
   (u/'hilega-api.service').write_text('unit')
   with self.assertRaisesRegex(RuntimeError,'PARTIAL_OR_INVALID'):h.service_mode(home,home)
 def test_all_units_select_supervision(self):
  with tempfile.TemporaryDirectory() as d:
   home=Path(d);u=home/'.config/systemd/user';u.mkdir(parents=True)
   for r in h.ROLES:(u/('hilega-'+r+'.service')).write_text('unit')
   self.assertTrue(h.service_mode(home,home))
 def test_activation_without_units_blocks_legacy(self):
  with tempfile.TemporaryDirectory() as d:
   home=Path(d);p=home/'hilega-persistent-supervision-stage-v1';p.mkdir();(p/'MIGRATION_APPROVED.json').write_text('{}')
   with self.assertRaisesRegex(RuntimeError,'SUPERVISION_CONFIG_MISSING'):h.service_mode(home,home)
 def test_detached_process_blocks(self):
  with self.assertRaisesRegex(RuntimeError,'DETACHED_PROCESS_PRESENT'):
   h.no_detached_processes([dict(role='api',pid=123)],{'api':{'MainPID':'0'}})
 def test_matched_service_process_accepted(self):
  h.no_detached_processes([dict(role='api',pid=123)],{'api':{'MainPID':'123'}})

if __name__=='__main__':unittest.main()
