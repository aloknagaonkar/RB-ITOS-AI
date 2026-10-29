from copy import deepcopy
from datetime import datetime
import importlib.util
from pathlib import Path
import unittest
from unittest.mock import patch

spec=importlib.util.spec_from_file_location('session',Path(__file__).with_name('session_test.py'))
s=importlib.util.module_from_spec(spec);spec.loader.exec_module(s)

class Fake:
    def __init__(self,fail=None,outcome=None):
        self.calls=[];self.fail=fail;self.outcome=outcome;self.now=0
    def step(self,name):
        self.calls.append(name)
        if self.fail==name:raise s.Blocked(name.upper()+'_FAILED')
    def preflight(self):self.step('preflight')
    def schedule_deadline(self,seconds):self.step('deadline')
    def reconcile_once(self):self.step('reconcile')
    def resume_parameters(self):self.step('parameters');return 1,'2026-10-29'
    def resume_once(self,v,d):self.step('resume');return '2026-10-29T11:05:00+05:30'
    def observe(self,at):self.step('observe');return self.outcome
    def clock(self):return self.now
    def wait(self):self.now+=60
    def pause_once(self):self.step('pause')
    def verify_paused(self):self.step('verify_pause')
    def cancel_deadline(self):self.step('cancel_deadline')

class Tests(unittest.TestCase):
    def status(self):
        return dict(workspace_mode='SIMULATION_ONLY',production_execution_enabled=False,production_orders_sent=False,
         control={'mode':'PAUSED'},source='EVIDENCE_PREPARATION_ONLY',
         application_preparation=dict(route='PREPARATION_ONLY',submission_gate='CLOSED_IN_CODE',production_execution_enabled=False,unresolved_preparation_count=0,shadow_held_cents=0),
         broker_execution_port=dict(transport_gate='CLOSED_IN_CODE',live_routing_implemented=False),
         bridge_health={'healthy':True},broker_observation=dict(status='LIVE_READ_ONLY',broker_connected=True,age_seconds=1,
         checks=[dict(check=k,status='PASS') for k in ('profile','orders','trades','positions','funds')],orders=[],positions=[],trades=[],
         funds=dict(status='PASS',cash_available_to_trade=0,field='data.available_to_trade.cash_available_to_trade.total')))
    def test_only_bus_variables_preserved_in_control_environment(self):
        result=s.control_environment(Path('/repo'),Path('/home/test'),dict(XDG_RUNTIME_DIR='/run/user/1001',DBUS_SESSION_BUS_ADDRESS='unix:path=/run/user/1001/bus',UPSTOX_ACCESS_TOKEN='secret'))
        self.assertEqual(result['XDG_RUNTIME_DIR'],'/run/user/1001')
        self.assertIn('DBUS_SESSION_BUS_ADDRESS',result)
        self.assertNotIn('UPSTOX_ACCESS_TOKEN',result)
    def test_run_requires_display_confirmation_before_io(self):
        with patch.object(s.sys,'argv',['session_test.py','run','--arm-preparation-only']),patch.object(s,'IO') as io:
            with self.assertRaisesRegex(s.Blocked,'UPSTOX_DISPLAY_CONFIRMATION_REQUIRED'):s.main()
            io.assert_not_called()
    def test_run_requires_explicit_arming_before_io(self):
        with patch.object(s.sys,'argv',['session_test.py','run','--confirm-upstox-zero-cash']),patch.object(s,'IO') as io:
            with self.assertRaisesRegex(s.Blocked,'EXPLICIT_PREPARATION_ARMING_REQUIRED'):s.main()
            io.assert_not_called()
    def acknowledgement(self):
        return dict(result=dict(request_id='resume-id',action='resume',status=dict(control=dict(
            mode='ARMED',version=42,session_date='2026-10-29',resumed_at='2026-10-29T11:21:00+05:30'))),
            snapshot=dict(control=dict(mode='PAUSED')))
    def parse_ack(self,value):
        return s.parse_resume_ack(value,'resume-id',41,'2026-10-29')
    def test_actual_api_result_envelope_accepted(self):
        c=self.parse_ack(self.acknowledgement())
        self.assertEqual(c['mode'],'ARMED')
    def test_snapshot_cannot_substitute_for_command_ack(self):
        value=self.acknowledgement();value['result']['status']['control']['mode']='PAUSED'
        value['snapshot']['control']['mode']='ARMED'
        with self.assertRaisesRegex(s.Blocked,'RESUME_ACK_STATE_INVALID'):self.parse_ack(value)
    def test_wrong_request_id_rejected(self):
        value=self.acknowledgement();value['result']['request_id']='other'
        with self.assertRaisesRegex(s.Blocked,'COMMAND_IDENTITY_MISMATCH'):self.parse_ack(value)
    def test_wrong_command_action_rejected(self):
        value=self.acknowledgement();value['result']['action']='pause'
        with self.assertRaisesRegex(s.Blocked,'COMMAND_IDENTITY_MISMATCH'):self.parse_ack(value)
    def test_wrong_version_rejected(self):
        value=self.acknowledgement();value['result']['status']['control']['version']=43
        with self.assertRaisesRegex(s.Blocked,'RESUME_ACK_STATE_INVALID'):self.parse_ack(value)
    def test_wrong_session_rejected(self):
        value=self.acknowledgement();value['result']['status']['control']['session_date']='2026-10-28'
        with self.assertRaisesRegex(s.Blocked,'RESUME_ACK_SESSION_MISMATCH'):self.parse_ack(value)
    def test_naive_resume_timestamp_rejected(self):
        value=self.acknowledgement();value['result']['status']['control']['resumed_at']='2026-10-29T11:21:00'
        with self.assertRaisesRegex(s.Blocked,'RESUME_TIMESTAMP_INVALID'):self.parse_ack(value)
    def test_missing_timestamp_rejected(self):
        value=self.acknowledgement();del value['result']['status']['control']['resumed_at']
        with self.assertRaisesRegex(s.Blocked,'RESUME_TIMESTAMP_MISSING'):self.parse_ack(value)
    def test_partial_envelopes_have_bounded_errors(self):
        for value in (None,{},dict(result={}),dict(result=dict(request_id='resume-id',action='resume'))):
            with self.assertRaises(s.Blocked):self.parse_ack(value)
    def test_real_io_resume_method_accepts_api_envelope_once(self):
        io=object.__new__(s.IO)
        io.ids={'resume':'resume-id'};io.output=Path('/unused-private-test')
        io.runner=type('Runner',(),{})()
        with patch.object(io.runner,'atomic',create=True) as write,patch.object(io,'control',return_value=self.acknowledgement()) as command:
            self.assertEqual(io.resume_once(41,'2026-10-29'),'2026-10-29T11:21:00+05:30')
            self.assertEqual(command.call_count,1)
            self.assertEqual(write.call_count,2)
    def test_bad_api_envelope_does_not_write_success_ack(self):
        io=object.__new__(s.IO)
        io.ids={'resume':'resume-id'};io.output=Path('/unused-private-test')
        io.runner=type('Runner',(),{})()
        with patch.object(io.runner,'atomic',create=True) as write,patch.object(io,'control',return_value={}) as command:
            with self.assertRaisesRegex(s.Blocked,'COMMAND_RESULT_MISSING'):io.resume_once(41,'2026-10-29')
            self.assertEqual(command.call_count,1)
            self.assertEqual(write.call_count,1)
    def test_good_status(self):s.validate_status(self.status())
    def test_positive_cash_blocks(self):
        v=self.status();v['broker_observation']['funds']['cash_available_to_trade']=100
        with self.assertRaisesRegex(s.Blocked,'ZERO_CASH_REQUIRED'):s.validate_status(v)
    def test_nonfinite_cash_blocks(self):
        for x in ('NaN','Infinity',None,True):self.assertFalse(s.zero(x))
    def test_live_transport_blocks(self):
        v=self.status();v['broker_execution_port']['transport_gate']='OPEN'
        with self.assertRaisesRegex(s.Blocked,'TRANSPORT_NOT_CLOSED'):s.validate_status(v)
    def test_stale_source_blocks(self):
        v=self.status();v['bridge_health']['healthy']=False
        with self.assertRaisesRegex(s.Blocked,'SOURCE_NOT_FRESH'):s.validate_status(v)
    def test_stale_broker_blocks(self):
        v=self.status();v['broker_observation']['age_seconds']=40
        with self.assertRaisesRegex(s.Blocked,'BROKER_OBSERVATION_STALE'):s.validate_status(v)
    def test_broker_position_blocks(self):
        v=self.status();v['broker_observation']['positions']=[{'quantity':1}]
        with self.assertRaisesRegex(s.Blocked,'BROKER_ACTIVITY'):s.validate_status(v)
    def test_armed_preflight_blocks(self):
        v=self.status();v['control']['mode']='ARMED'
        with self.assertRaisesRegex(s.Blocked,'CONTROLLER_MODE_INVALID'):s.validate_status(v)
    def test_timer_scheduled_before_resume(self):
        io=Fake(outcome={'status':'ZERO_CASH_REJECTION_OBSERVED'})
        result=s.execute_session(io,60)
        self.assertLess(io.calls.index('deadline'),io.calls.index('resume'))
        self.assertLess(io.calls.index('verify_pause'),io.calls.index('cancel_deadline'))
        self.assertTrue(result['pause_verified'])
        self.assertFalse(result['fresh_signal_admission_verified'])
    def test_preflight_failure_never_resumes(self):
        io=Fake(fail='preflight');s.execute_session(io,60)
        self.assertNotIn('resume',io.calls)
    def test_timer_failure_never_resumes(self):
        io=Fake(fail='deadline');s.execute_session(io,60)
        self.assertNotIn('resume',io.calls)
    def test_reconcile_failure_pauses(self):
        io=Fake(fail='reconcile');s.execute_session(io,60)
        self.assertNotIn('resume',io.calls);self.assertIn('pause',io.calls)
    def test_uncertain_resume_not_retried_and_pauses(self):
        io=Fake(fail='resume');result=s.execute_session(io,60)
        self.assertEqual(io.calls.count('resume'),1);self.assertIn('pause',io.calls)
        self.assertTrue(result['resume_attempted'])
    def test_observation_error_pauses(self):
        io=Fake(fail='observe');result=s.execute_session(io,60)
        self.assertIn('pause',io.calls);self.assertEqual(result['status'],'STOPPED_FOR_REVIEW')
    def test_pause_failure_retains_independent_deadline(self):
        io=Fake(fail='pause');result=s.execute_session(io,60)
        self.assertNotIn('cancel_deadline',io.calls)
        self.assertEqual(result['status'],'PAUSE_UNCONFIRMED_REQUIRES_REVIEW')
    def test_pause_verification_failure_retains_deadline(self):
        io=Fake(fail='verify_pause');s.execute_session(io,60)
        self.assertNotIn('cancel_deadline',io.calls)
    def test_deadline_cleanup_error_preserves_result(self):
        io=Fake(fail='cancel_deadline');result=s.execute_session(io,60)
        self.assertTrue(result['pause_verified']);self.assertIn('deadline_cleanup_warning',result)
    def test_no_signal_is_inconclusive(self):
        result=s.execute_session(Fake(),60)
        self.assertEqual(result['status'],'INCONCLUSIVE_NO_ELIGIBLE_ENTRY');self.assertTrue(result['pause_verified'])
    def test_market_window(self):
        s.validate_window(datetime.fromisoformat('2026-10-29T11:05:00+05:30'),300)
        with self.assertRaises(s.Blocked):s.validate_window(datetime.fromisoformat('2026-10-29T14:50:00+05:30'),300)
    def test_invalid_duration(self):
        for n in (0,601,True):
            with self.assertRaises(s.Blocked):s.validate_window(datetime.fromisoformat('2026-10-29T11:05:00+05:30'),n)
    def case(self):
        at='2026-10-29T11:05:00+05:30'
        event=dict(id='new',role='ENTRY',event_at='2026-10-29T11:10:00+05:30')
        audit=dict(at='2026-10-29T11:10:01+05:30',status='BLOCKED',reasons=['NO_CASH_CAPACITY','HALF_CASH_CAP_EXCEEDED'])
        return at,event,audit
    def test_cash_outcome_requires_new_entry_link(self):
        at,event,audit=self.case()
        result=s.classify([audit],{'new'},[event],at,'PAUSED')
        self.assertEqual(result['status'],'ZERO_CASH_REJECTION_OBSERVED')
    def test_missing_link_not_passed(self):
        at,event,audit=self.case()
        with self.assertRaisesRegex(s.Blocked,'ENTRY_LINK_NOT_PROVEN'):s.classify([audit],{'new'},[],at,'PAUSED')
    def test_pre_resume_event_not_passed(self):
        at,event,audit=self.case();event['event_at']=at
        with self.assertRaisesRegex(s.Blocked,'PRE_RESUME_EVENT'):s.classify([audit],{'new'},[event],at,'PAUSED')
    def test_multiple_consumed_events_not_passed(self):
        at,event,audit=self.case()
        with self.assertRaisesRegex(s.Blocked,'AMBIGUOUS'):s.classify([audit],{'new','other'},[event],at,'PAUSED')
    def test_reversal_block_is_not_cash_test_success(self):
        at,event,audit=self.case();audit['reasons']=['EXIT_OR_REVERSAL_REQUIRES_LIVE_OWNERSHIP']
        self.assertEqual(s.classify([audit],{'new'},[event],at,'PAUSED')['status'],'INCONCLUSIVE_OTHER_BLOCKER_OR_OPERATOR_PAUSE')
    def test_extra_cash_blocker_not_passed(self):
        at,event,audit=self.case();audit['reasons'].append('QUOTE_STALE')
        self.assertNotEqual(s.classify([audit],{'new'},[event],at,'PAUSED')['status'],'ZERO_CASH_REJECTION_OBSERVED')

if __name__=='__main__':unittest.main()
