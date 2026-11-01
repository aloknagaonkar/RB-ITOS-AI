import unittest
from copy import deepcopy
from market_lab.hilega_v2_replay_presentation_v1 import project_session
from market_lab.hilega_v2_alignment_replay_v1 import MODEL
class PresentationTests(unittest.TestCase):
 def data(self):
  def a(cp,owner,transitions,price,ind):return dict(checkpoint=cp,minute_timestamp='2026-10-06T09:29:00+05:30',owner_before=owner,owner_after=transitions[-1]['direction'] if transitions and transitions[-1]['event']=='ENTRY_ACTIVE' else 'NONE',nifty_close=price,indicators=ind,checks=[],transitions=transitions)
  return dict(model=MODEL,session_date='2026-10-06',trades=[dict(entry_time='2026-10-06T09:30:00+05:30',direction='BULLISH',setup_source='V1_CANONICAL')],audit=[
   a('2026-10-06T09:30:00+05:30','NONE',[dict(event='ENTRY_ACTIVE',direction='BULLISH',price=100)],100,dict(rsi9=60,ema3=55,wma21=50)),
   a('2026-10-06T10:00:00+05:30','BULLISH',[dict(event='EXIT_CLOSED',direction='BULLISH',price=95,points=-5),dict(event='ENTRY_ACTIVE',direction='BEARISH',price=95)],95,dict(rsi9=40,ema3=45,wma21=50))],performance_summary=[{'net_points':-5}])
 def test_exit_entry_order_and_exact_timestamp(self):
  x=project_session(self.data());self.assertEqual(x['report_count'],3)
  self.assertEqual([r['transitions'][0]['event_type'] for r in x['reports']],['ENTRY_V2_ALIGNMENT','V2_DUAL_EXIT','ENTRY_V2_ALIGNMENT'])
  ex,en=x['reports'][1:];self.assertEqual(ex['checkpoint'],en['checkpoint']);self.assertNotEqual(ex['audit_row_id'],en['audit_row_id'])
  self.assertEqual(ex['linked_signal_bar'],'2026-10-06T09:30:00+05:30');self.assertEqual(en['linked_signal_bar'],en['checkpoint'])
  self.assertEqual(ex['strategy']['owner_after'],'NONE');self.assertEqual(en['strategy']['owner_before'],'NONE')
 def test_previous_values_and_no_fabricated_option_fills(self):
  x=project_session(self.data());r=x['reports'][1]
  self.assertEqual(r['indicators']['previous_rsi9'],60);self.assertEqual(r['indicators']['previous_ema3_rsi'],55)
  self.assertIsNone(r['option_lifecycle']);self.assertTrue(r['conditions']['authoritative_strategy_steps'])
 def test_projection_does_not_change_strategy_results_or_source(self):
  source=self.data();before=deepcopy(source);x=project_session(source)
  self.assertEqual(source,before);self.assertEqual(x['trades'],source['trades']);self.assertEqual(x['performance_summary'],source['performance_summary'])
 def test_expired_setup_is_rejected_and_reasons_preserved(self):
  x=self.data();x['audit']=x['audit'][:1];x['audit'][0]['transitions']=[];x['audit'][0]['checks']=[dict(direction='BULLISH',status='WAIT',reasons=['WINDOW_EXPIRED'],current_gap=4,previous_gap=5,gap_delta=-1,gap_expanding_pass=False)]
  r=project_session(x)['reports'][0];self.assertEqual(r['strategy']['events_emitted'],['WMA_GAP_NO_ENTRY_BY_T10'])
  steps=r['conditions']['strategy_steps'];self.assertTrue(any(z['label'].endswith('gap expansion') and z['status']=='FAIL' for z in steps));self.assertIn('WINDOW_EXPIRED',steps[-1]['explanation'])
 def test_empty_day_keeps_monitoring_audit(self):
  x=self.data();x['trades']=[]
  for a in x['audit']:a['transitions']=[];a['owner_before']='NONE';a['owner_after']='NONE'
  y=project_session(x);self.assertEqual(y['report_count'],2);self.assertTrue(y['reports'][0]['conditions']['strategy_steps'])
if __name__=='__main__':unittest.main()
