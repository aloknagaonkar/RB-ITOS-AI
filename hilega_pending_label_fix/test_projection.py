import unittest,sys,ast,json,os
from pathlib import Path
sys.path.insert(0,str(Path(__file__).parent))
from hilega_pending_direction_display_v1 import resolve_audit_direction
class Tests(unittest.TestCase):
 def test_bearish_pending(self):self.assertEqual(resolve_audit_direction(dict(owner_after='NONE',bullish_armed=False,bearish_armed=True)),'BEARISH')
 def test_bullish_pending(self):self.assertEqual(resolve_audit_direction(dict(owner_after='NONE',bullish_armed=True,bearish_armed=False)),'BULLISH')
 def test_active_owner_priority(self):self.assertEqual(resolve_audit_direction(dict(owner_after='BULLISH',bearish_armed=True)),'BULLISH')
 def test_exit_prior_owner(self):self.assertEqual(resolve_audit_direction(dict(owner_after='NONE',owner_before='BEARISH',accepted_events='STRUCTURAL_EXIT_BEARISH_RSI_CROSS_ABOVE_WMA21')),'BEARISH')
 def test_check_fallback(self):self.assertEqual(resolve_audit_direction(dict(owner_after='NONE',wma_gap_checks=[dict(direction='BEARISH')])),'BEARISH')
 def test_state_fallback(self):self.assertEqual(resolve_audit_direction(dict(bearish_state='BEARISH_PATH1_ARMED',bullish_state='PATH1_IDLE')),'BEARISH')
 def test_unknown_not_invented(self):self.assertIsNone(resolve_audit_direction({}))
 def test_both_directions_ambiguous(self):self.assertIsNone(resolve_audit_direction(dict(bullish_armed=True,bearish_armed=True,wma_gap_checks=[dict(direction='BEARISH'),dict(direction='BULLISH')])))
 def test_actual_api_projection_on_vm_fixtures(self):
  root=Path(os.environ.get('LABEL_FIX_REPO','source/RB-ITOS-AI-feature-pcr-foundation'))
  sys.path.insert(0,str(root/'backend'));p=root/'backend/market_lab/hilega_historical_ui_api_v1.py'
  n=next(n for n in ast.parse(p.read_text()).body if isinstance(n,ast.FunctionDef) and n.name=='_directional_report');scope={};exec(compile(ast.fix_missing_locations(ast.Module(body=[n],type_ignores=[])),str(p),'exec'),scope)
  for fixture in json.loads(Path(__file__).with_name('vm-fixtures.json').read_text()):
   st=fixture['strategy'];row=dict(bar_timestamp=fixture['checkpoint'],owner_before=st['owner_before'],owner_after=st['owner_after'],bullish_armed=st['bullish_armed'],bearish_armed=st['bearish_armed'],bullish_state=st['bullish_state'],bearish_state=st['bearish_state'],accepted_events=','.join(st['events_emitted']),wma_gap_checks=fixture['conditions']['wma_gap_checks'])
   self.assertEqual(scope['_directional_report'](row)['strategy']['direction'],'BEARISH')
if __name__=='__main__':
 if len(sys.argv)>1 and not sys.argv[1].startswith('-'):
  # Preserve repo argument for the API test; unittest must not interpret it as test name.
  repo_arg=sys.argv[1];sys.argv=sys.argv[:1]
  original=Path.cwd();import os;os.environ['LABEL_FIX_REPO']=repo_arg
 unittest.main()
