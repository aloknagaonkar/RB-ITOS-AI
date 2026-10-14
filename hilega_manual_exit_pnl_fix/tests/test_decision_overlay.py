import copy,importlib.util,unittest
from pathlib import Path
HERE=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('decision_overlay',HERE/'files/backend/market_lab/hilega_manual_exit_decision_v1.py');m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
SIDE='HILEGA_V2_ALIGNMENT_DUAL_EXIT'
class Tests(unittest.TestCase):
 def setUp(self):
  self.rows={'2026-10-14T13:48:00+05:30':dict(bar_timestamp='2026-10-14T13:48:00+05:30',strategy_id=SIDE,accepted_events='ENTRY_PATH1_ROUTE_B_STRUCTURAL',owner_after='BULLISH',close=22652.3),'2026-10-14T14:45:00+05:30':dict(bar_timestamp='2026-10-14T14:45:00+05:30',strategy_id=SIDE,action='BULLISH_ACTIVE',owner_before='BULLISH',owner_after='BULLISH',accepted_events='')}
  self.r=dict(request_id='R',session_date='2026-10-14',strategy_id=SIDE,requested_at='2026-10-14T14:42:13+05:30',completed_at='2026-10-14T14:43:11+05:30',status='READY_FOR_FRESH_SIGNAL',trade_ids=['T'],legs=[dict(direction='BULLISH',event_timestamp='2026-10-14T13:48:00+05:30')])
 def apply(self,records=None,acks=None):return m.overlay_manual_exit_rows(self.rows,records or [],'2026-10-14',requests=[self.r],acks=acks or {})
 def test_acknowledged_reset_adds_exit_at_actual_completion(self):
  self.apply(acks={'R':{}});x=next(x for x in self.rows.values() if x.get('accepted_events')=='MANUAL_EXIT_BULLISH');self.assertEqual(x['bar_timestamp'],self.r['completed_at']);self.assertEqual(x['owner_after'],'NONE');self.assertEqual(x['event_details'][0]['exit_reason'],'MANUAL_EXIT');self.assertIsNone(x['close']);self.assertEqual(x['event_details'][0]['entry_price'],22652.3)
 def test_request_alone_does_not_report_exit(self):
  self.r.pop('completed_at');self.r['status']='VERIFYING';self.apply();self.assertFalse(any(x.get('accepted_events')=='MANUAL_EXIT_BULLISH' for x in self.rows.values()));self.assertEqual(self.rows['2026-10-14T14:45:00+05:30']['owner_after'],'BULLISH')
 def test_flat_confirmation_without_reset_ack_is_still_pending(self):
  self.r['status']='WAITING_FOR_STRATEGY_RESET';self.apply();self.assertFalse(any(x.get('action')=='BULLISH_EXIT' for x in self.rows.values()))
 def test_reset_audit_is_sufficient_proof(self):
  self.apply(records=[dict(stage='DIRECTIONAL_MANUAL_EXIT_RESET',status='PROCESSED',payload=dict(strategy_id=SIDE,request_id='R',completed_at=self.r['completed_at'],trade_owner_before='BULLISH'))]);self.assertTrue(any(x.get('accepted_events')=='MANUAL_EXIT_BULLISH' for x in self.rows.values()))
 def test_old_continuation_stops_but_source_state_preserved(self):
  self.apply(acks={'R':{}});r=self.rows['2026-10-14T14:45:00+05:30'];self.assertEqual(r['owner_after'],'NONE');self.assertEqual(r['manual_exit_source_state']['owner_after'],'BULLISH')
 def test_fresh_entry_starts_new_lifecycle(self):
  self.rows['2026-10-14T14:45:00+05:30'].update(accepted_events='ENTRY_BEARISH_ROUTE_B_STRUCTURAL',action='BEARISH_ENTRY',owner_after='BEARISH');self.rows['2026-10-14T14:50:00+05:30']=dict(bar_timestamp='2026-10-14T14:50:00+05:30',strategy_id=SIDE,action='BEARISH_ACTIVE',owner_after='BEARISH',accepted_events='');self.apply(acks={'R':{}});self.assertEqual(self.rows['2026-10-14T14:50:00+05:30']['owner_after'],'BEARISH')
 def test_no_records_no_change(self):
  before=copy.deepcopy(self.rows);m.overlay_manual_exit_rows(self.rows,[],'2026-10-14',requests=[],acks={});self.assertEqual(self.rows,before)
 def test_bearish_manual_exit(self):
  self.r['legs'][0]['direction']='BEARISH';self.apply(acks={'R':{}});self.assertTrue(any(x.get('accepted_events')=='MANUAL_EXIT_BEARISH' for x in self.rows.values()))
 def test_other_session_does_not_change_current(self):
  before=copy.deepcopy(self.rows);self.r['session_date']='2026-10-13';self.apply(acks={'R':{}});self.assertEqual(self.rows,before)
 def test_repeated_projection_does_not_duplicate_exit(self):
  self.apply(acks={'R':{}});self.apply(acks={'R':{}});self.assertEqual(sum(x.get('accepted_events')=='MANUAL_EXIT_BULLISH' for x in self.rows.values()),1)
if __name__=='__main__':unittest.main()
