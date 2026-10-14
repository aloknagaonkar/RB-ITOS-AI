import unittest,json,tempfile,types,runpy,subprocess,sys,contextlib
from pathlib import Path
from datetime import datetime
from unittest.mock import patch
import hilega_sandbox_daily_autoarm_v1 as helper

class Tests(unittest.TestCase):
 def run_case(self,kill=False):
  self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name)
  self.control=dict(armed=True,session_date='2026-10-13',strategy_id=helper.EXPECTED,kill_switch=kill,sandbox_only=True,live_execution_enabled=False)
  self.arms=[];self.worker=types.SimpleNamespace(control=types.SimpleNamespace(read=lambda:dict(self.control)),store=types.SimpleNamespace(path=self.root/'basket.jsonl'),status=lambda:dict(open_legs=0,uncertain_requests=0))
  package=types.ModuleType('testpackage');package.__path__=[];basket=types.ModuleType('testpackage.hilega_upstox_sandbox_basket_v2')
  basket.strategy=lambda env:helper.EXPECTED;basket.SandboxConfig=types.SimpleNamespace(from_env=lambda env:types.SimpleNamespace(assert_ready=lambda confirmation:None));basket.DEFAULT_SOURCE=Path('audit.jsonl')
  def arm(day,*args):self.arms.append(day);self.control.update(armed=True,session_date=day.isoformat())
  basket.arm=arm
  self.package=package;self.basket=basket
 def tick(self,minute):
  now=datetime(2026,10,14,9,minute,tzinfo=helper.IST)
  with patch.object(helper,'datetime') as clock,patch.object(helper,'__package__','testpackage'),patch.dict(sys.modules,{'testpackage':self.package,'testpackage.hilega_upstox_sandbox_basket_v2':self.basket}),patch.object(helper.Path,'cwd',return_value=self.root),patch('builtins.print'):
   clock.now.return_value=now
   return helper.maybe_autoarm_in_worker(self.worker,Path('.env'),lock_factory=lambda *a,**kw:contextlib.nullcontext())
 def test_tick_arms_once_same_bucket_skips(self):
  self.run_case();self.assertEqual(self.tick(1)['status'],'ARMED_TODAY');self.assertIsNone(self.tick(2));self.assertEqual(len(self.arms),1)
 def test_later_bucket_preserves_same_day_cursor(self):
  self.run_case();self.tick(0);self.assertEqual(self.tick(5)['status'],'ALREADY_ARMED_TODAY');self.assertEqual(len(self.arms),1)
 def test_after_open_skips_automatic_arming(self):
  self.run_case();self.assertIsNone(self.tick(16));self.assertFalse(self.arms)
 def test_manual_kill_switch_remains_blocked(self):
  self.run_case(kill=True);self.assertEqual(self.tick(0)['status'],'BLOCKED_MANUAL_KILL_SWITCH');self.assertFalse(self.arms)
 def test_installer_changes_serve_loop_and_removes_only_our_cron(self):
  with tempfile.TemporaryDirectory() as td:
   root=Path(td);module=root/'backend/market_lab/hilega_upstox_sandbox_basket_v2.py';module.parent.mkdir(parents=True)
   module.write_text('def main():\n        while True:\n            try:result=w.run_once()\n            except Exception:pass\n')
   old='0 1 * * * echo keep\n# BEGIN HILEGA_SANDBOX_DAILY_AUTOARM\nold-autoarm\n# END HILEGA_SANDBOX_DAILY_AUTOARM\n';installed=[]
   def runner(args,**kw):
    if args==['crontab','-l']:return subprocess.CompletedProcess(args,0,stdout=old,stderr='')
    if args==['crontab','-']:installed.append(kw['input']);return subprocess.CompletedProcess(args,0)
    raise AssertionError(args)
   with patch('sys.argv',['install.py','--repo',str(root)]),patch('shutil.which',return_value='/usr/bin/crontab'),patch('subprocess.run',side_effect=runner),patch('builtins.print'):runpy.run_path(str(Path(__file__).with_name('install.py')),run_name='__main__')
   self.assertIn('maybe_autoarm_in_worker(w,a.env_file)',module.read_text());self.assertEqual(installed,['0 1 * * * echo keep\n'])
if __name__=='__main__':unittest.main()
