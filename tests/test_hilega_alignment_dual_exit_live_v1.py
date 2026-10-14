import json, tempfile, unittest
from datetime import datetime, date, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from market_lab import hilega_v2_alignment_replay_v1 as historical
from market_lab import hilega_alignment_dual_exit_live_v1 as live
from market_lab.hilega_milega_strategy_v1 import SessionState, StrategyEvent, IndicatorSnapshot
from market_lab.hilega_milega_bearish_strategy_v1 import BearishSessionState
from market_lab.hilega_sandbox_event_bridge_v1 import BridgeConfig, HilegaSandboxEventBridgeV1, IntentStore, BridgeError
from market_lab.live_shadow_step_audit_v1 import ShadowStepAuditStoreV1
from market_lab.domain import IST

class AlignmentLiveTests(unittest.TestCase):
    def coordinator(self, folder):
        c=live.HilegaAlignmentDualExitLiveCoordinator(market_sources=SimpleNamespace(),
            option_expiry=None,step_audit_path=Path(folder)/'audit',health_path=Path(folder)/'health')
        c._audit=lambda *args,**kw:None
        c._start_option=lambda **kw:None
        c._close_option=lambda **kw:None
        return c

    def test_shared_gate_and_exit(self):
        self.assertIs(live.WmaGapGate,historical.WmaGapGate)
        self.assertIs(live.ExitFirstCanonical,historical.ExitFirstCanonical)
        self.assertIs(live.dual_exit,historical.dual_exit)
        self.assertFalse(live.dual_exit('BULLISH',IndicatorSnapshot(30,50,40)))
        self.assertTrue(live.dual_exit('BULLISH',IndicatorSnapshot(30,35,40)))
        self.assertFalse(live.dual_exit('BEARISH',IndicatorSnapshot(50,40,40)))
        self.assertTrue(live.dual_exit('BEARISH',IndicatorSnapshot(50,45,40)))

    def test_cutoff_closes_actual_owner_without_canonical_position(self):
        with tempfile.TemporaryDirectory() as d:
            c=self.coordinator(d);at=datetime(2026,10,9,14,55,tzinfo=IST)
            c.gate.owner='BEARISH';c.gate.active=dict(time=at-timedelta(hours=1),price=100)
            c.canonical.session_date=at.date()
            c.canonical.bullish.session=SessionState(session_date=at.date())
            c.canonical.bearish.session=BearishSessionState(session_date=at.date())
            c.canonical.trade_owner='NONE'
            decision=c.process_cutoff(at,intraday=[SimpleNamespace(timestamp=at,open=90)])
            self.assertEqual(len(decision.accepted_events),1)
            self.assertEqual(decision.accepted_events[0].points,10)
            self.assertEqual(decision.accepted_events[0].exit_reason,'SESSION_CUTOFF_1455')
            self.assertEqual(c.gate.owner,'NONE');self.assertTrue(c.gate.locked)
            self.assertIsNone(c.process_cutoff(at,intraday=[]))

    def test_bridge_strategy_isolation_order_and_idempotency(self):
        with tempfile.TemporaryDirectory() as d:
            src=Path(d)/'source';out=Path(d)/'intents';store=ShadowStepAuditStoreV1(src)
            at=datetime(2026,10,9,10,tzinfo=IST)
            def add(events,strategy):
                store.append(event_time=at,checkpoint=at,stage='DIRECTIONAL_DECISION',
                    status='PROCESSED',payload=dict(strategy_id=strategy,
                    decision_timestamp=at.isoformat(),accepted_events=events))
            add(['ENTRY_PATH1_ROUTE_B_STRUCTURAL'],'HILEGA_DIRECTIONAL_SHADOW_V1')
            add(['ENTRY_PATH1_ROUTE_B_STRUCTURAL'],live.STRATEGY_ID)
            add(['STRUCTURAL_EXIT_RSI_CROSS_BELOW_WMA21','ENTRY_BEARISH_ROUTE_B_STRUCTURAL'],live.STRATEGY_ID)
            bridge=HilegaSandboxEventBridgeV1(BridgeConfig(True,src,out))
            bridge.run_once();rows=IntentStore(out).rows()
            self.assertEqual([r['event_type'] for r in rows],['ENTRY','ENTRY','EXIT','ENTRY'])
            self.assertTrue(all(r['decision']=='WOULD_SUBMIT' for r in rows))
            self.assertNotEqual(rows[0]['trade_id'],rows[1]['trade_id'])
            self.assertEqual(rows[2]['trade_id'],rows[1]['trade_id'])
            self.assertEqual(bridge.run_once()['written'],0)

    def test_day_reset_clears_alignment_and_warning(self):
        with tempfile.TemporaryDirectory() as d:
            c=self.coordinator(d);c.episode={'BULLISH':True,'BEARISH':True};c.warning_time='yesterday'
            c._reset_policy_session()
            self.assertEqual(c.episode,{'BULLISH':False,'BEARISH':False});self.assertIsNone(c.warning_time)

    def test_restore_filters_old_strategy(self):
        with tempfile.TemporaryDirectory() as d:
            c=self.coordinator(d)
            self.assertEqual(c.strategy_id,live.STRATEGY_ID)
            self.assertEqual(c._safe()['strategy_id'],live.STRATEGY_ID)
            self.assertFalse(c._safe()['execution_enabled'])

    def test_next_session_bootstrap_unlocks(self):
        with tempfile.TemporaryDirectory() as d:
            c=self.coordinator(d)
            old=datetime(2026,10,8,9,15,tzinfo=IST)
            raw=[dict(timestamp=(old+timedelta(minutes=i)).isoformat(),open=100,high=101,low=99,close=100,volume=1) for i in range(375)]
            p=Path(d)/'2026-10-08.json';p.write_text(json.dumps(dict(candles=raw)))
            c._bootstrapped_date=old.date();c.gate.locked=True;c.episode={'BULLISH':True,'BEARISH':True}
            c.sources=SimpleNamespace(nifty_intraday_1m=lambda **kw:[])
            c._restore_audited_option_state=lambda **kw:{}
            fresh=old+timedelta(days=1)
            with patch.object(live,'cache_index',return_value={'2026-10-08':p}):
                c.bootstrap(fresh)
            self.assertFalse(c.gate.locked)
            self.assertEqual(c.gate.owner,'NONE')
            self.assertEqual(c.canonical.session_date,fresh.date())
            self.assertFalse(any(c.episode.values()))

    def test_same_exit_boundary_requires_two_strong_adjacent_minutes(self):
        t=datetime(2026,10,9,10,tzinfo=IST)
        g=live.WmaGapGate()
        g.previous=dict(minute=t-timedelta(minutes=1),snapshot=IndicatorSnapshot(34,35,40),wma_change=-.9)
        event=StrategyEvent('ENTRY_BEARISH_ROUTE_B_STRUCTURAL',t,None,'IDLE','ARMED')
        g.signal(event,t+timedelta(minutes=1))
        entries,checks=g.evaluate(minute=t,current=IndicatorSnapshot(32,33,39),
            reference=IndicatorSnapshot(42,41,40),price=99,exit_boundary=True)
        self.assertEqual(len(entries),1)
        self.assertTrue(checks[0]['same_exit_boundary_confirmation'])

if __name__=='__main__':
    unittest.main()
