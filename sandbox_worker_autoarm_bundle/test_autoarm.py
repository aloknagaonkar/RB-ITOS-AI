import unittest,copy,tempfile,runpy,sys,subprocess
from datetime import datetime
from pathlib import Path
from unittest.mock import patch
from hilega_sandbox_daily_autoarm_v1 import IST,EXPECTED,decide,process
NOW=datetime(2026,10,14,9,0,tzinfo=IST)
CONTROL=dict(armed=True,session_date='2026-10-13',strategy_id=EXPECTED,kill_switch=False,sandbox_only=True,live_execution_enabled=False)
class Adapter:
 def __init__(self):self.c=copy.deepcopy(CONTROL);self.s=dict(open_legs=0,uncertain_requests=0);self.calls=[];self.is_running=True
 def control(self):return self.c
 def status(self):return self.s
 def active_strategy(self):return EXPECTED
 def running(self):return self.is_running
 def assert_config_ready(self):self.calls.append('config')
 def arm(self,day):self.calls.append('arm');self.c.update(armed=True,session_date=day.isoformat())
 def start_worker(self):self.calls.append('start');self.is_running=True
class Tests(unittest.TestCase):
 def setUp(self):self.a=Adapter()
 def test_previous_day_autoarms_today(self):
  r=process(NOW,self.a,apply=True);self.assertEqual(r['status'],'ARMED_TODAY');self.assertEqual(self.a.c['session_date'],'2026-10-14')
 def test_same_day_does_not_reset_source_baseline(self):
  self.a.c.update(session_date='2026-10-14',baseline_source_sequence=123)
  r=process(NOW,self.a,apply=True);self.assertEqual(r['status'],'ALREADY_ARMED_TODAY');self.assertNotIn('arm',self.a.calls);self.assertEqual(self.a.c['baseline_source_sequence'],123)
 def test_open_legs_block_arming(self):
  self.a.s['open_legs']=1;r=process(NOW,self.a,apply=True);self.assertEqual(r['status'],'BLOCKED_OPEN_LEGS');self.assertFalse(self.a.calls)
 def test_uncertain_request_blocks_arming(self):
  self.a.s['uncertain_requests']=1;r=process(NOW,self.a,apply=True);self.assertEqual(r['status'],'BLOCKED_UNCERTAIN_REQUESTS')
 def test_block_flag_is_not_cleared(self):
  self.a.c['entries_blocked']=True;r=process(NOW,self.a,apply=True);self.assertEqual(r['status'],'BLOCKED_RECONCILIATION_REQUIRED');self.assertTrue(self.a.c['entries_blocked'])
 def test_manual_kill_switch_preserved(self):
  self.a.c['kill_switch']=True;r=process(NOW,self.a,apply=True);self.assertEqual(r['status'],'BLOCKED_MANUAL_KILL_SWITCH')
 def test_strategy_mismatch_blocks(self):
  self.a.c['strategy_id']='OLD';r=process(NOW,self.a,apply=True);self.assertEqual(r['status'],'BLOCKED_STRATEGY_MISMATCH')
 def test_non_sandbox_or_live_flag_blocks(self):
  for update in [dict(sandbox_only=False),dict(live_execution_enabled=True)]:
   self.a.c={**CONTROL,**update};r=process(NOW,self.a,apply=True);self.assertEqual(r['status'],'BLOCKED_NOT_SANDBOX_ONLY')
 def test_weekend_skipped(self):
  r=process(NOW.replace(day=17),self.a,apply=True);self.assertEqual(r['status'],'SKIP_NON_TRADING_DATE')
 def test_disabled_date_skipped(self):
  r=process(NOW,self.a,apply=True,disabled_days=['2026-10-14']);self.assertEqual(r['status'],'SKIP_NON_TRADING_DATE')
 def test_no_late_rearm(self):
  r=process(NOW.replace(hour=10),self.a,apply=True);self.assertEqual(r['status'],'SKIP_OUTSIDE_PREMARKET_WINDOW')
 def test_check_does_not_arm_or_start(self):
  self.a.is_running=False;r=process(NOW,self.a,apply=False);self.assertEqual(r['status'],'ARM_TODAY');self.assertNotIn('arm',self.a.calls);self.assertNotIn('start',self.a.calls)
 def test_missing_worker_starts_after_arm(self):
  self.a.is_running=False;r=process(NOW,self.a,apply=True);self.assertEqual(self.a.calls,['config','arm','start']);self.assertTrue(r['worker_running'])
 def test_existing_arm_can_restart_worker_without_rearm(self):
  self.a.c['session_date']='2026-10-14';self.a.is_running=False;process(NOW,self.a,apply=True);self.assertNotIn('arm',self.a.calls);self.assertIn('start',self.a.calls)
 def test_failed_config_prevents_arming(self):
  self.a.assert_config_ready=lambda:(_ for _ in ()).throw(ValueError('invalid config'))
  with self.assertRaises(ValueError):process(NOW,self.a,apply=True)
  self.assertNotIn('arm',self.a.calls)
 def test_existing_legacy_guard_failure_is_not_bypassed(self):
  self.a.arm=lambda day:(_ for _ in ()).throw(ValueError('LEGACY_UNCERTAIN_REQUEST_RECONCILE_BEFORE_SWITCH'))
  with self.assertRaises(ValueError):process(NOW,self.a,apply=True)

if __name__=='__main__':unittest.main()
