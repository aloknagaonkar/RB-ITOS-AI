import copy
from datetime import datetime,time
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

SCRIPT=Path(__file__).resolve().parents[1]/'audit_3m.py'
spec=importlib.util.spec_from_file_location('audit_3m',SCRIPT)
a=importlib.util.module_from_spec(spec);spec.loader.exec_module(a)


def record(sequence=1,status='PROCESSED',version='new',checks=None,events=None):
    frame=dict(open=100.,high=103.,low=98.,close=99.,ema10=100.,previous_ema10=101.,
        rsi9=45.,previous_rsi9=50.,ema3_rsi=48.,previous_ema3_rsi=51.,
        wma21_rsi=55.,previous_wma21_rsi=56.)
    return dict(stage='DIRECTIONAL_DECISION',status=status,sequence=sequence,record_hash=str(sequence),
        event_time='2026-11-23T09:21:00+05:30',payload=dict(
        decision_timestamp='2026-11-23T09:21:00+05:30',bar_timestamp='2026-11-23T09:18:00+05:30',
        strategy_version=version,reconstructed=status=='RECOVERED',price_ema_frame=frame,
        trade_owner_before='NONE',trade_owner_after='NONE',
        wma_gap_checks=checks or [],event_details=events or [],pending_candidates={}))


class AuditTests(unittest.TestCase):
    def test_latest_version_selected_without_mixing_old(self):
        version,available,rows,raw=a.selected_decisions([record(1,version='old'),record(2,version='new')],'latest')
        self.assertEqual(version,'new');self.assertEqual(len(rows),1)
        self.assertEqual(available,['old','new'])

    def test_later_recovery_does_not_replace_forward_evidence(self):
        old=record(1);new=record(2,status='RECOVERED')
        version,available,rows,raw=a.selected_decisions([old,new],'new')
        self.assertEqual(rows[0]['sequence'],1);self.assertEqual(len(raw),2)

    def test_recovery_is_labelled(self):
        self.assertEqual(a.side_report(record(status='RECOVERED'),'BEARISH')['evidence'],'RECONSTRUCTED')

    def test_missing_evaluation_is_not_a_recorded_failure(self):
        v=a.side_report(record(),'BULLISH')
        self.assertEqual(v['status'],'NOT_EVALUATED')
        self.assertEqual(v['recorded_blockers'],[])
        self.assertIn('fresh_alignment',v['diagnostics']['failed_diagnostics'])
        self.assertIsNone(v['recorded_vote_count'])

    def test_bearish_direction_signs(self):
        d=a.diagnostics(record()['payload'],'BEARISH')
        self.assertEqual(d['directional_gap'],7.)
        self.assertEqual(d['directional_wma_strength'],1.)
        self.assertEqual(d['gap_expansion'],2.)
        self.assertEqual(d['diagnostic_vote_count'],3)

    def test_missing_prices_are_not_replaced_by_last_minute_ohlc(self):
        r=record();r['payload']['price_ema_frame']={}
        r['payload']['minute_ohlcv']=dict(open=1,high=2,low=1,close=2)
        d=a.diagnostics(r['payload'],'BEARISH')
        self.assertIsNone(d['open']);self.assertIsNone(d['checks']['candle_colour'])

    def test_followup_wait_reason_is_preserved(self):
        c=dict(direction='BEARISH',status='EMA10_ENTRY_WAIT',strength_gap_pass_count=3,
            reasons=['WAIT_NEXT_COMPLETED_3M_CLOSE'],ema10_entry=dict(
                passed=False,reasons=['WAIT_NEXT_COMPLETED_3M_CLOSE'],candle_colour_pass=True))
        v=a.side_report(record(checks=[c]),'BEARISH')
        self.assertEqual(v['recorded_blockers'],['WAIT_NEXT_COMPLETED_3M_CLOSE'])
        self.assertEqual(v['phase'],'INITIAL_FRAME')

    def test_price_route_can_confirm_with_low_fresh_votes(self):
        c=dict(direction='BEARISH',status='ENTRY',strength_gap_pass_count=1,
            gap_positive_pass=False,wma_threshold_pass=False,gap_expanding_pass=True,
            reasons=[],ema10_entry=dict(passed=True,followup_rule='FOLLOWUP',
                followup_price_pass=True,fresh_strength_gap_pass=False,entry_confirmation_route='PRICE'))
        event=dict(event_type='ENTRY_BEARISH_ROUTE_B_STRUCTURAL',event_time='2026-11-23T09:21:00+05:30')
        v=a.side_report(record(checks=[c],events=[event]),'BEARISH')
        self.assertEqual(v['status'],'ENTRY_CONFIRMED');self.assertEqual(v['route'],'PRICE')
        self.assertEqual(v['recorded_blockers'],[]);self.assertFalse(v['recorded_flags']['gap_positive_pass'])

    def test_reversal_monitor_is_not_omitted_or_mislabeled_as_main_gate(self):
        r=record();r['payload']['opposite_confirmation']=dict(checks=[dict(
            direction='BULLISH',status='WAIT',reasons=['STRENGTH_GAP_FEWER_THAN_TWO'])])
        v=a.side_report(r,'BULLISH')
        self.assertEqual(v['channel'],'BULLISH_REVERSAL_MONITOR')
        self.assertEqual(v['recorded_blockers'],['STRENGTH_GAP_FEWER_THAN_TWO'])

    def test_multiple_attempts_retained_and_last_blocker_reported(self):
        checks=[dict(direction='BEARISH',status='WAIT',reasons=['first']),
                dict(direction='BEARISH',status='EMA10_ENTRY_WAIT',reasons=['last'])]
        v=a.side_report(record(checks=checks),'BEARISH')
        self.assertEqual(v['recorded_blockers'],['last']);self.assertEqual(len(v['main_attempts']),2)

    def test_both_direction_rows_and_exit_flags_are_preserved(self):
        r=record();r['payload']['exit_validation']=dict(action='HOLD_WMA_LE40',normal_exit_pass=False)
        for side in a.SIDES:self.assertEqual(a.side_report(r,side)['exit_validation']['action'],'HOLD_WMA_LE40')

    def test_complete_prefix_and_malformed_count_are_reported(self):
        with tempfile.TemporaryDirectory() as folder:
            p=Path(folder)/'audit';complete=(json.dumps(record())+'\n').encode()
            p.write_bytes(complete+b'bad\n'+b'{"partial":')
            rows,source=a.read_snapshot(p,'2026-11-23')
            self.assertEqual(len(rows),1);self.assertEqual(source['malformed_lines'],1)
            self.assertTrue(source['incomplete_tail_ignored'])
            self.assertEqual(source['complete_prefix_bytes'],len(complete)+4)

    def test_old_decision_written_today_is_not_mixed_into_today(self):
        with tempfile.TemporaryDirectory() as folder:
            p=Path(folder)/'audit';r=record();r['payload']['decision_timestamp']='2026-11-20T09:21:00+05:30'
            p.write_text(json.dumps(r)+'\n')
            rows,source=a.read_snapshot(p,'2026-11-23');self.assertEqual(rows,[])

    def test_report_does_not_mutate_source_record(self):
        r=record();before=copy.deepcopy(r)
        for side in a.SIDES:a.side_report(r,side)
        self.assertEqual(r,before)

    def test_html_escapes_raw_audit_strings(self):
        r=record();r['payload']['note']='<script>evil()</script>'
        output=a.html_report('<test>',{},[r],[a.side_report(r,s) for s in a.SIDES])
        self.assertNotIn('<script>evil()',output)
        self.assertIn('&lt;script&gt;',output)

    def test_coverage_does_not_create_fake_pass_fail_rows(self):
        now=datetime(2026,11,23,9,24,tzinfo=a.IST)
        result=a.coverage('2026-11-23',now,time(9,15),time(15,30),{'2026-11-23T09:21:00+05:30'})
        self.assertEqual(result['completed_boundaries_as_of_snapshot'],3)
        self.assertEqual(len(result['boundaries_not_present_in_selected_snapshot']),2)

    def test_cli_exports_all_formats_and_leaves_audit_unchanged(self):
        with tempfile.TemporaryDirectory() as folder:
            folder=Path(folder);source=folder/'audit.jsonl';source.write_text(json.dumps(record())+'\n')
            before=source.read_bytes()
            run=subprocess.run([sys.executable,str(SCRIPT),'--day','2026-11-23',
                '--audit',str(source),'--out',str(folder/'reports')],capture_output=True,text=True)
            self.assertEqual(run.returncode,0,run.stderr)
            self.assertEqual(source.read_bytes(),before)
            for name in ('audit.json','audit.csv','audit.html','audit.txt'):
                self.assertEqual(len(list((folder/'reports').rglob(name))),1)
            self.assertEqual(len(list((folder/'reports').glob('*.zip'))),1)


if __name__=='__main__':unittest.main()
