import os,sys,json,tempfile,unittest
from pathlib import Path
from datetime import datetime,timedelta
from types import SimpleNamespace
from dataclasses import dataclass
from unittest.mock import patch

HERE=Path(__file__).resolve().parents[1]
sys.path.insert(0,os.environ.get('HILEGA_NATIVE_TEST_ROOT',str(Path('work_3m_update/native_candidate/backend').resolve())))
sys.path.insert(0,str(HERE))
from market_lab.hilega_three_minute_v1 import hilega_combined_policy_v1 as p
from market_lab.hilega_rsi_two_route_v1 import reference
from market_lab.hilega_three_minute_v1.hilega_milega_strategy_v1 import FiveMinuteBar
import manage

@dataclass
class Decision:
    accepted_events:tuple=()
    suppressed_events:tuple=()
    trade_owner_after:str='NONE'
class Canonical:
    def __init__(self):self.bullish=SimpleNamespace(previous_indicators=SimpleNamespace(ema3_rsi=50.))
    def on_bar(self,b):return Decision()

def frame(side='CE',**extra):
    ce=side=='CE';r=dict(open=100 if ce else 108,close=108 if ce else 100,high=110,low=98,
        ema30_high=105,ema30_low=103,wma21_rsi9=60 if ce else 40,
        **{'rsi'+str(period):60 if ce else 40 for period in reference.PERIODS})
    r.update(extra);return r

def market(frames):
    neutral=frame(rsi5=50,rsi9=50,rsi14=50,rsi21=50,rsi28=50,wma21_rsi9=50)
    fs=frames+[neutral]*(125-len(frames));start=datetime.fromisoformat('2026-11-23T09:15:00+05:30');rows=[];bars=[]
    for i,f in enumerate(fs):
        at=start+timedelta(minutes=3*i);bars.append(dict(start=at.isoformat(),**{k:f[k] for k in ('open','high','low','close')}))
        for j in range(3):rows.append(dict(timestamp=(at+timedelta(minutes=j)).isoformat(),**{k:f[k] for k in ('open','high','low','close')}))
    class Supplied:
        def __init__(self):self.i=0
        def update(self,b):
            f=fs[self.i];self.i+=1;return {k:v for k,v in f.items() if k not in ('open','high','low','close')}
    return bars,rows,Supplied

def native(frames,blocks=()):
    bars,rows,supplied=market(frames);tracker=p.PriceFrames();tracker.tracker=supplied();tracker.minute_rows=rows;g=p.make_gate(tracker.frames);c=Canonical();results=[]
    for i,b in enumerate(bars):
        tracker.entry_block_reason='EXTERNAL_ENTRY_BLOCK' if i in blocks else None
        results.append(p.advance_boundary(c,g,FiveMinuteBar(datetime.fromisoformat(b['start']),b['open'],b['high'],b['low'],b['close']),None,tracker))
    return tracker,g,results

class NativeRules(unittest.TestCase):
    def test_reference_policy_parity_and_both_direction_audit(self):
        frames=[frame('CE'),frame('PE'),frame('PE'),frame('CE')]
        bars,rows,cls=market(frames);expected=reference.replay('2026-11-23',bars,rows,[],indicator_factory=cls)
        tracker,g,result=native(frames)
        self.assertEqual(len(tracker.engine.trades),len(expected['trades']))
        for actual,want in zip(tracker.engine.trades,expected['trades']):
            for key in ('route_name','side','entry_time','exit_time','entry_price','exit_price','points','peak_positive_points','giveback_points','exit_reasons'):
                self.assertEqual(actual[key],want[key])
        self.assertEqual(len(result),125);self.assertTrue(all(len(r['checks'])==2 for r in result))
        self.assertEqual(g.owner,'NONE')
    def test_normal_any_two_and_bypass_both_sides(self):
        for side in ('CE','PE'):
            f=frame(side);threshold=60 if side=='CE' else 40
            f.update(rsi14=50,rsi21=50,rsi28=50)
            t,_,_=native([f]);self.assertEqual(t.engine.trades[0]['route_name'],'Normal Route')
            f=frame(side,wma21_rsi9=40 if side=='CE' else 60)
            t,_,_=native([f]);self.assertEqual(t.engine.trades[0]['route_name'],'WMA_bypass')
    def test_midpoint_requires_both_rsis_and_strict_price(self):
        for side in ('CE','PE'):
            ce=side=='CE';f=frame(side,open=104,close=103 if ce else 105,high=110,low=98,
                ema30_high=120,ema30_low=90,rsi5=40 if ce else 60,rsi9=40 if ce else 60,
                rsi14=50,rsi21=50,rsi28=50)
            t,_,r=native([frame(side),f]);self.assertEqual(t.engine.trades[0]['exit_reasons'],['SIGNAL_MIDPOINT_AND_RSI5_RSI9'])
            for key in ('rsi5','rsi9'):
                changed=dict(f,**{key:50});_,_,r=native([frame(side),changed]);self.assertFalse(r[1]['exit_validation']['signal_midpoint_rsi_confirmed_exit'])
            changed=dict(f,close=104);_,_,r=native([frame(side),changed]);self.assertFalse(r[1]['exit_validation']['signal_midpoint_price_breach'])
    def test_opposite_exit_precedes_entry_using_existing_event_types(self):
        from market_lab.hilega_sandbox_event_bridge_v1 import ENTRY_EVENTS,EXIT_EVENTS
        t,_,r=native([frame('CE'),frame('PE')])
        self.assertEqual(t.engine.trades[0]['exit_reasons'],['QUALIFIED_OPPOSITE_ENTRY'])
        self.assertTrue(all(e.event_type in EXIT_EVENTS for e in r[1]['exits']))
        self.assertTrue(all(e.event_type in ENTRY_EVENTS for e in r[1]['entries']))
    def test_external_block_does_not_change_indicator_values(self):
        _,_,plain=native([frame('CE')]);_,_,blocked=native([frame('CE')],blocks=(0,))
        self.assertEqual(plain[0]['frame'],blocked[0]['frame']);self.assertFalse(blocked[0]['entries'])
        self.assertIn('EXTERNAL_ENTRY_BLOCK',blocked[0]['checks'][0]['reasons'])
    def test_manual_gate_reset_releases_model_and_fresh_signal(self):
        bars,rows,cls=market([frame('CE'),frame('CE')]);t=p.PriceFrames();t.tracker=cls();t.minute_rows=rows;g=p.make_gate(t.frames);c=Canonical()
        b=lambda x:FiveMinuteBar(datetime.fromisoformat(x['start']),x['open'],x['high'],x['low'],x['close'])
        first=p.advance_boundary(c,g,b(bars[0]),None,t)
        g.owner='NONE';g.active=None;p.reset_pending(g)
        second=p.advance_boundary(c,g,b(bars[1]),None,t)
        self.assertEqual(len(second['entries']),1);self.assertNotEqual(first['entries'][0].details['native_trade_id'],second['entries'][0].details['native_trade_id'])
    def test_reference_open_is_required_before_indicator_mutation(self):
        bars,rows,cls=market([frame('CE')]);t=p.PriceFrames();t.tracker=cls();t.minute_rows=rows[:3];g=p.make_gate(t.frames)
        b=bars[0]
        with self.assertRaises(KeyError):p.advance_boundary(Canonical(),g,FiveMinuteBar(datetime.fromisoformat(b['start']),b['open'],b['high'],b['low'],b['close']),None,t)
        self.assertEqual(t.tracker.i,0)

class NativeContracts(unittest.TestCase):
    def test_approved_env_bytes_are_unchanged(self):
        original=b'UPSTOX_ACCESS_TOKEN=keep-secret\nLIVE_SHADOW_STRATEGY=HILEGA_V2_ALIGNMENT_DUAL_EXIT\nHILEGA_PRODUCTION_WORKSPACE_MODE=SIMULATION_ONLY\nHILEGA_STRIKE_SELECTOR_MODE=FIVE_ACTUAL_SANDBOX_LEGS\n'
        updated=manage.selected_env(original)
        self.assertEqual(updated,original)
    def test_reject_changed_or_duplicate_active_settings(self):
        for b in (b'LIVE_SHADOW_STRATEGY=OTHER\n',b'LIVE_SHADOW_STRATEGY=HILEGA_V2_ALIGNMENT_DUAL_EXIT\n'*2):
            with self.assertRaises(ValueError):manage.selected_env(b)
    def test_install_failure_never_calls_apply(self):
        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(sys,'argv',['manage.py','--install','--repo',tmp]),patch.object(manage,'prepare',side_effect=ValueError('BUILD_FAILED')),patch.object(manage,'apply') as apply:
                with self.assertRaisesRegex(ValueError,'BUILD_FAILED'):manage.main()
                apply.assert_not_called()
    def test_native_screens_have_no_added_workspace(self):
        root=Path(os.environ.get('HILEGA_NATIVE_TEST_ROOT','work_3m_update/native_candidate/backend')).parent
        for name in ('hilegaHistoricalReplay.tsx','hilegaMilegaShadow.tsx'):
            text=(root/'frontend/src'/name).read_text();self.assertNotIn('HilegaRsiTwoRouteWorkspace',text);self.assertNotIn('LegacyHilega',text)
        self.assertIn("useState<'LIVE'|'V1'|'V2'|'V2_ALIGN'>('V2_ALIGN')",(root/'frontend/src/hilegaHistoricalReplay.tsx').read_text())
    def test_local_ledger_guard_reports_flat_then_open_without_broker_reads(self):
        import check_flat
        previous=Path.cwd()
        with tempfile.TemporaryDirectory() as tmp:
            try:
                os.chdir(tmp)
                self.assertEqual(check_flat.probe()['status'],'LOCAL_LEDGERS_FLAT')
                journal=Path('data/live-observation/hilega-upstox-sandbox-v2/basket-events.jsonl');journal.parent.mkdir(parents=True)
                journal.write_text(json.dumps(dict(status='ACCEPTED',event_type='ENTRY',trade_id='test',role=0,request_id='test-request'))+'\n')
                report=check_flat.probe()
                self.assertEqual(report['status'],'BLOCKED_EXISTING_POSITIONS_OR_REQUESTS')
                self.assertEqual(report['counts']['open_legs'],1)
                self.assertFalse(report['broker_requests_sent'])
            finally:os.chdir(previous)

    def test_old_and_new_reversals_still_bridge_exit_first(self):
        from market_lab.hilega_sandbox_event_bridge_v1 import BridgeConfig,HilegaSandboxEventBridgeV1
        from market_lab.live_shadow_step_audit_v1 import ShadowStepAuditStoreV1
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);source=root/'source.jsonl';output=root/'intents.jsonl';store=ShadowStepAuditStoreV1(source)
            for n,strategy in enumerate((manage.OLD,manage.NEW)):
                at=datetime.fromisoformat('2026-11-23T10:00:00+05:30')+timedelta(minutes=6*n)
                for offset,names in ((0,[p.ENTRY['CE']]),(3,[p.EXIT['CE'],p.ENTRY['PE']])):
                    t=at+timedelta(minutes=offset)
                    store.append(event_time=t,checkpoint=t,stage='DIRECTIONAL_DECISION',status='PROCESSED',payload=dict(strategy_id=strategy,strategy_version=p.VERSION,policy_id=p.POLICY_ID,decision_timestamp=t.isoformat(),accepted_events=names))
            HilegaSandboxEventBridgeV1(BridgeConfig(True,source,output)).run_once()
            rows=[json.loads(l) for l in output.read_text().splitlines()]
            for strategy in (manage.OLD,manage.NEW):
                events=[r['event_type'] for r in rows if r['strategy_id']==strategy]
                self.assertEqual(events,['ENTRY','EXIT','ENTRY'])
            self.assertTrue(all(r['decision']=='WOULD_SUBMIT' for r in rows))
    def test_version_guard_blocks_old_intent_before_transport(self):
        from market_lab.hilega_upstox_sandbox_basket_v2 import BasketWorker
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);control=root/'control.json';control.write_text(json.dumps(dict(strategy_id=manage.NEW,strategy_version=p.VERSION,policy_id=p.POLICY_ID,session_date='2026-11-23')))
            w=BasketWorker(control=control,journal=root/'basket.jsonl',env=root/'.env')
            intent=dict(intent_id='i',event_id='e',trade_id='t',event_type='ENTRY',direction='BULLISH',event_timestamp='2026-11-23T10:00:00+05:30',source_sequence=1,strategy_version='OLD',policy_id=p.POLICY_ID)
            w.process(intent,[intent],None,None)
            self.assertEqual(w.store.rows()[-1]['status'],'SKIPPED_STRATEGY_VERSION_MISMATCH')


class ApiAndRollback(unittest.TestCase):
    def test_api_probe_waits_for_display_cache_without_starting_lifespan(self):
        from contextlib import asynccontextmanager
        from fastapi import FastAPI
        from fastapi.responses import JSONResponse
        import check_api
        started=[];calls=[]
        @asynccontextmanager
        async def lifespan(app):
            started.append(True)
            raise AssertionError('LIFESPAN_MUST_NOT_START')
            yield
        app=FastAPI(lifespan=lifespan)
        @app.get('/api/live-shadow/hilega-directional/status')
        def status():
            calls.append(True)
            if len(calls)==1:return JSONResponse(status_code=503,content={'detail':{'code':'UI_AUDIT_CACHE_WARMING_OR_ERROR','error':None}})
            return dict(active_strategy_id=manage.NEW,strategy_version=p.VERSION)
        @app.get('/api/live-shadow/hilega-historical/sessions')
        def sessions():return {'sessions':[]}
        self.assertEqual(check_api.check_app(app)['status'],'NATIVE_HILEGA_API_CHECK_PASS')
        self.assertEqual(len(calls),2);self.assertEqual(started,[])
    def test_rollback_restores_sources_and_preserves_journals(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);backup=root/'backup';backup.mkdir()
            target=root/'backend/changed.py';target.parent.mkdir();target.write_bytes(b'new')
            original=backup/'original/backend/changed.py';original.parent.mkdir(parents=True);original.write_bytes(b'old')
            journal=root/'data/journal.jsonl';journal.parent.mkdir();journal.write_bytes(b'unchanged')
            r=dict(repo=str(root),basket_was_running=False,files={'backend/changed.py':dict(before=manage.digest(b'old'),after=manage.digest(b'new'))})
            with patch.object(manage,'ctl'),patch.object(manage,'basket_pid',return_value=None):manage.rollback(backup,r)
            self.assertEqual(target.read_bytes(),b'old');self.assertEqual(journal.read_bytes(),b'unchanged')
    def test_rollback_rejects_post_install_edits_before_service_changes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);(root/'changed.py').write_bytes(b'edited')
            r=dict(repo=str(root),files={'changed.py':dict(before=manage.digest(b'old'),after=manage.digest(b'new'))})
            with patch.object(manage,'ctl') as ctl:
                with self.assertRaisesRegex(ValueError,'ROLLBACK_SOURCE_CHANGED'):manage.rollback(root,r)
                ctl.assert_not_called()

class OptionLifecycleContract(unittest.TestCase):
    def test_original_five_leg_ce_and_pe_lifecycles_accept_native_events(self):
        from market_lab.hilega_alignment_dual_exit_live_v1 import HilegaAlignmentDualExitLiveCoordinator
        from market_lab.hilega_three_minute_v1.hilega_milega_strategy_v1 import StrategyEvent
        from market_lab.live_option_minute_source_v1 import CompletedOptionMinute
        at=datetime.fromisoformat('2026-11-23T09:18:00+05:30');expiry=at.date()
        class Sources:
            def option_contracts(self,underlying,day):
                return [dict(expiry=str(day),instrument_type=side,strike_price=25000+50*role,instrument_key=side+str(role)) for side in ('CE','PE') for role in range(-2,3)]
            def option_intraday_1m(self,key):
                return [CompletedOptionMinute(key,at+timedelta(minutes=i),10.,11.,9.,10.) for i in range(4)]
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);c=HilegaAlignmentDualExitLiveCoordinator(market_sources=Sources(),option_expiry=expiry,step_audit_path=root/'audit.jsonl',health_path=root/'health.jsonl')
            bar=FiveMinuteBar(at-timedelta(minutes=3),24990,25010,24980,25000)
            for side,direction,attribute in (('CE','BULLISH','ce_shadow'),('PE','BEARISH','pe_shadow')):
                event=StrategyEvent(p.ENTRY[side],at,'Normal Route','IDLE','ACTIVE',price=25000,entry_time=at,entry_price=25000)
                c._start_option(direction=direction,now=at+timedelta(seconds=30),bar=bar,event=event,audit=True)
                snap=getattr(c,attribute).snapshot
                self.assertIsNotNone(snap)
                self.assertTrue(snap.active,snap.issue);self.assertEqual(len(snap.legs),5)
                self.assertEqual(snap.signal_boundary,at.isoformat());self.assertEqual(snap.source,'Normal Route')
                boundary=at+timedelta(minutes=3)
                c._close_option(direction=direction,now=boundary+timedelta(seconds=30),exit_boundary=boundary,exit_reason='SIGNAL_MIDPOINT_AND_RSI5_RSI9',audit=True)
                closed=getattr(c,attribute).snapshot
                self.assertEqual(closed.status,'CLOSED');self.assertEqual(len(closed.legs),5)

class CutoverAndRecovery(unittest.TestCase):
    def snapshot(self,path,recovered,proof=()):
        from market_lab.hilega_rsi_two_route_v1 import native_inputs
        at=datetime.fromisoformat('2026-11-23T09:15:00+05:30')
        rows=[SimpleNamespace(timestamp=at+timedelta(minutes=i),open=100.,high=101.,low=99.,close=100.,volume=1) for i in range(4)]
        seen=[]
        c=SimpleNamespace(price_frames=p.PriceFrames(),_last_minute=None,step_audit=SimpleNamespace(read_all=lambda:list(proof)),_health=lambda *a,**k:None)
        def advance(minute,bars,**kwargs):
            c._last_minute=minute.timestamp;seen.append(c.price_frames.entry_block_reason)
        c._advance=advance
        with patch.object(native_inputs,'ACTIVATION',path):native_inputs.consume(c,rows,at+timedelta(minutes=3,seconds=30),recovered=recovered)
        return c,seen
    def test_uncommitted_cutover_blocks_new_entries(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'activation.json';path.write_text(json.dumps(dict(activated_at='2026-11-23T09:15:00+05:30',committed=False)))
            c,seen=self.snapshot(path,False)
            self.assertTrue(all(x=='NATIVE_CUTOVER_NOT_COMMITTED' for x in seen))
            self.assertNotIn('close',c.price_frames.minute_rows[-1])
    def test_recovery_requires_prior_native_entry_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'activation.json';path.write_text(json.dumps(dict(activated_at='2026-11-23T09:15:00+05:30',committed=True)))
            _,seen=self.snapshot(path,True);self.assertEqual(seen[-1],'RECOVERY_WITHOUT_AUDITED_ENTRY')
            proof=[dict(stage='DIRECTIONAL_DECISION',status='PROCESSED',payload=dict(strategy_id=manage.NEW,strategy_version=p.VERSION,decision_timestamp='2026-11-23T09:18:00+05:30',accepted_events=[p.ENTRY['CE']]))]
            _,seen=self.snapshot(path,True,proof);self.assertIsNone(seen[-1])
    def test_pre_cutover_bar_cannot_enter_after_commit(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'activation.json';path.write_text(json.dumps(dict(activated_at='2026-11-23T09:18:00+05:30',committed=True)))
            _,seen=self.snapshot(path,False);self.assertEqual(seen[-1],'PRE_ACTIVATION_CANDLE_NOT_TRADABLE')

class CutoverBoundary(unittest.TestCase):
    def test_first_full_bar_has_no_extra_opening_filter(self):
        for value,want in (('09:14:59','09:15'),('09:15:00','09:15'),('09:18:00','09:18'),('09:18:01','09:21'),('10:01:02','10:03')):
            at=datetime.fromisoformat('2026-11-23T'+value+'+05:30')
            self.assertEqual(manage.cutover_boundary(at).strftime('%H:%M'),want)


class ApprovedConfigurationAlias(unittest.TestCase):
    def test_only_reviewed_alignment_selection_maps_to_new_strategy(self):
        from market_lab.hilega_active_strategy_v1 import effective_strategy
        self.assertEqual(effective_strategy(manage.OLD),manage.NEW)
        self.assertEqual(effective_strategy(' '+manage.OLD.lower()+' '),manage.NEW)
        for value in (manage.NEW,'HILEGA_WMA_GAP_V2_LIVE_SHADOW','HILEGA_DIRECTIONAL_SHADOW_V1','UNKNOWN',None,''):
            self.assertEqual(effective_strategy(value),value)
    def test_basket_env_and_dotenv_fallback_have_same_effective_id(self):
        from market_lab.hilega_upstox_sandbox_basket_v2 import strategy
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'.env';body=('LIVE_SHADOW_STRATEGY='+manage.OLD+'\nHILEGA_PRODUCTION_WORKSPACE_MODE=SIMULATION_ONLY\n').encode();path.write_bytes(body)
            with patch.dict(os.environ,{},clear=True):self.assertEqual(strategy(path),manage.NEW)
            with patch.dict(os.environ,{'LIVE_SHADOW_STRATEGY':manage.OLD},clear=True):self.assertEqual(strategy(path),manage.NEW)
            self.assertEqual(path.read_bytes(),body)
    def test_real_api_reports_native_policy_from_approved_legacy_setting(self):
        from market_lab.api import app
        import check_api
        with patch.dict(os.environ,{'LIVE_SHADOW_STRATEGY':manage.OLD}):
            self.assertEqual(check_api.check_app(app)['strategy_id'],manage.NEW)
    def test_failed_health_check_keeps_actual_identity_in_diagnostic(self):
        import io
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            response=io.BytesIO(json.dumps(dict(active_strategy_id=manage.OLD,strategy_version='old')).encode())
            with patch.object(manage,'urlopen',return_value=response):
                with self.assertRaisesRegex(ValueError,'NATIVE_API_HEALTH_CHECK_FAILED'):
                    manage.http_check('http://127.0.0.1',root,max_wait=0)
            report=json.loads((root/'api-health.json').read_text())
            self.assertEqual(report['status'],'FAILED');self.assertEqual(report['observations'][-1]['active_strategy_id'],manage.OLD)

class SupervisorApprovalRegression(unittest.TestCase):
    def test_full_apply_preserves_env_approval_while_promoting_policy(self):
        from contextlib import redirect_stdout,ExitStack
        import io
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);repo=root/'repo';stage=root/'stage';package=root/'package'
            repo.mkdir();stage.mkdir();package.mkdir();(package/'manifest.json').write_bytes(b'{}')
            env=b'UPSTOX_ACCESS_TOKEN=keep-secret\nLIVE_SHADOW_STRATEGY=HILEGA_V2_ALIGNMENT_DUAL_EXIT\nHILEGA_PRODUCTION_WORKSPACE_MODE=SIMULATION_ONLY\n'
            (repo/'.env').write_bytes(env)
            control=repo/manage.CONTROL;control.parent.mkdir(parents=True);control.write_text(json.dumps(dict(strategy_id=manage.OLD,strategy_version='old',policy_id='old',execution_mode='FIVE_ACTUAL_SANDBOX_LEGS',armed=False,session_date='2026-11-23')))
            for folder,value in ((repo,b'old-code'),(stage,b'new-code')):
                path=folder/'backend/sample.py';path.parent.mkdir();path.write_bytes(value)
            prepared=dict(repo=str(repo),stage=str(stage),package_sha256=manage.digest(b'{}'),
                files={'backend/sample.py':dict(before=manage.digest(b'old-code'),after=manage.digest(b'new-code'))},assets={},
                configuration_lease={'.env':manage.digest(env),manage.CONTROL:manage.digest(control.read_bytes())})
            (stage/'prepared.json').write_text(json.dumps(prepared))
            def supervisor_guard(base,candidate):
                if (repo/'.env').read_bytes()!=env:raise ValueError('ENV_CHANGED_REVIEW_REQUIRED')
                self.assertEqual((repo/'backend/sample.py').read_bytes(),b'new-code')
            with ExitStack() as stack:
                stack.enter_context(patch.object(manage,'HERE',package))
                stack.enter_context(patch.object(manage,'inventory',return_value={}))
                stack.enter_context(patch.object(manage,'protected',return_value={}))
                stack.enter_context(patch.object(manage,'check_protected'))
                stack.enter_context(patch.object(manage,'flat',return_value={'status':'LOCAL_LEDGERS_FLAT'}))
                stack.enter_context(patch.object(manage,'basket_pid',return_value=None))
                stack.enter_context(patch.object(manage,'ctl'))
                stack.enter_context(patch.object(manage,'unit',return_value={'ActiveState':'active','MainPID':'7'}))
                stack.enter_context(patch.object(manage.time,'sleep'))
                stack.enter_context(patch.object(manage,'http_check',side_effect=supervisor_guard))
                stack.enter_context(redirect_stdout(io.StringIO()))
                manage.apply(SimpleNamespace(repo=repo,stage=stage,api_url='http://127.0.0.1:8123'))
            self.assertEqual((repo/'.env').read_bytes(),env)
            promoted=json.loads(control.read_text());self.assertEqual(promoted['strategy_id'],manage.NEW)
            self.assertEqual(promoted['execution_mode'],'FIVE_ACTUAL_SANDBOX_LEGS');self.assertFalse(promoted['armed'])
            receipt=next((repo/'data/recovery').glob('hilega-rsi-native-install-*/receipt.json'))
            transaction=json.loads(receipt.read_text());self.assertEqual(transaction['status'],'NATIVE_HILEGA_STRATEGY_UPDATED')
            self.assertNotIn('.env',transaction['files']);self.assertFalse((receipt.parent/'original/.env').exists())
            self.assertTrue(json.loads((repo/manage.ACTIVATION).read_text())['committed'])

class WorkerFactoryCompatibility(unittest.TestCase):
    def test_approved_legacy_env_selects_real_native_coordinator(self):
        from market_lab import live_shadow_worker_v1 as worker
        from unittest.mock import MagicMock
        class SelectedNative(Exception):pass
        with patch.dict(os.environ,{'LIVE_SHADOW_STRATEGY':manage.OLD,'HILEGA_MARKET_EVIDENCE_ENABLED':'0','MIDPOINT_SHADOW_ENABLED':'0'},clear=True):
            source=MagicMock()
            with patch.object(worker,'load_dotenv'),patch.object(worker,'make_engine',return_value=object()),patch.object(worker,'initialize'),patch.object(worker,'Session'),patch.object(worker,'active_config',return_value=(1,SimpleNamespace(provider='upstox'),False)),patch.object(worker,'UpstoxLiveShadowSourcesV1',return_value=source),patch.object(worker,'_resolve_hilega_option_expiry',return_value=(datetime.now().date(),'TEST')),patch.object(worker,'HilegaAlignmentDualExitLiveCoordinator',side_effect=SelectedNative) as coordinator:
                with self.assertRaises(SelectedNative):worker.run()
                coordinator.assert_called_once();source.close.assert_called_once()

if __name__=='__main__':unittest.main()
