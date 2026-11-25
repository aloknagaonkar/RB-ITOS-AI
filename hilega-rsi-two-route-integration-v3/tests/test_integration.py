import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from datetime import date, datetime, timedelta

PACKAGE=Path(__file__).resolve().parents[1]
sys.path.insert(0,os.environ.get('HILEGA_RSI_TEST_MODULE_ROOT',str(PACKAGE/'files/backend/market_lab')))
from hilega_rsi_two_route_v1.engine import Engine
from hilega_rsi_two_route_v1 import reference
from hilega_rsi_two_route_v1.data import aggregate
from hilega_rsi_two_route_v1.live import Store
from hilega_rsi_two_route_v1.calendar import IST, validate_rows, required_sessions


def minutes(day='2026-11-23',count=375):
    start=datetime.fromisoformat(day+'T09:15:00+05:30')
    rows=[]
    for i in range(count):
        price=25000+((i%53)-26)*2
        rows.append(dict(timestamp=(start+timedelta(minutes=i)).isoformat(),open=price,high=price+4,
                         low=price-4,close=price+1,volume=None))
    return rows


class IntegrationTests(unittest.TestCase):
    def test_batch_incremental_restore_parity(self):
        rows=minutes();warm=aggregate(minutes('2026-11-20'))*2
        expected=reference.replay('2026-11-23',aggregate(rows),rows,warm)
        engine=Engine('2026-11-23',warm)
        for b in aggregate(rows):
            engine.advance(b,rows)
            engine=Engine.restore(json.loads(json.dumps(engine.snapshot())))
        self.assertEqual(engine.result()['trades'],expected['trades'])
        self.assertEqual(engine.result()['audit'],expected['audit'])
        self.assertEqual(engine.result()['summary'],expected['summary'])

    def test_stream_restart_duplicate_and_revision(self):
        rows=minutes();warm=aggregate(minutes('2026-11-20'))*2;day=date(2026,11,23)
        with tempfile.TemporaryDirectory() as tmp:
            store=Store(tmp)
            for i in range(3,375,3):
                now=datetime.fromisoformat(rows[i]['timestamp'])+timedelta(seconds=2)
                result=store.ingest(day,rows[:i+1],now,warm,{'seed':'test'})
                store=Store(tmp)
                repeated=store.ingest(day,rows[:i+1],now,warm,{'seed':'test'})
                self.assertEqual(result['audit'],repeated['audit'])
                self.assertEqual(repeated['health']['new_audits'],0)
            now=datetime.fromisoformat('2026-11-23T15:30:05+05:30')
            r=store.ingest(day,rows,now,warm,{'seed':'test'})
            expected=reference.replay(str(day),aggregate(rows),rows,warm)
            self.assertEqual(r['trades'],expected['trades']);self.assertIsNone(r['owner'])
            changed=[dict(r) for r in rows];changed[0]['open']+=1
            before=store.view(day)['audit']
            with self.assertRaisesRegex(ValueError,'SOURCE_REVISION'):
                store.ingest(day,changed,now,warm,{'seed':'test'})
            self.assertEqual(store.view(day)['audit'],before)
            with self.assertRaisesRegex(ValueError,'SEED_CHANGED'):
                store.ingest(day,rows,now,warm,{'seed':'other'})

    def test_missing_mark_waits_and_forming_data_excluded(self):
        rows=minutes();day=date(2026,11,23);now=datetime.fromisoformat(rows[3]['timestamp'])
        with tempfile.TemporaryDirectory() as tmp:
            store=Store(tmp)
            r=store.ingest(day,rows[:3],now,[],{})
            self.assertEqual(r['health']['status'],'PENDING_REFERENCE_OPEN');self.assertEqual(len(r['audit']),0)
            forming=dict(rows[3],high=99999,low=1,close=99998)
            r=store.ingest(day,rows[:3]+[forming],now,[],{})
            self.assertEqual(len(r['audit']),1)
            self.assertEqual(r['audit'][0]['frame']['high'],max(x['high'] for x in rows[:3]))
            # Even a forming open used at entry/exit is an immutable modeled reference.
            bad=[dict(x) for x in rows[:4]];bad[3]['open']+=1
            with self.assertRaisesRegex(ValueError,'REFERENCE_OPEN_REVISION'):
                store.ingest(day,bad,now,[],{})

    def test_gap_future_bad_ohlc_are_blocked(self):
        rows=minutes();day=date(2026,11,23);now=datetime.fromisoformat(rows[10]['timestamp'])
        with tempfile.TemporaryDirectory() as tmp:
            store=Store(tmp)
            for bad in (rows[1:4], rows[:2]+rows[3:5],rows[:12], [dict(rows[0],high=1)]):
                with self.assertRaises(ValueError):store.ingest(day,bad,now,[],{})

    def test_special_session_and_mirrored_rules(self):
        rows=minutes('2026-11-08',70)
        start=datetime.fromisoformat('2026-11-08T14:20:00+05:30')
        for i,r in enumerate(rows):r['timestamp']=(start+timedelta(minutes=i)).isoformat()
        validate_rows(rows,date(2026,11,8))
        e=Engine('2026-11-08')
        for b in aggregate(rows[1:]):e.advance(b,rows)
        self.assertEqual(len(e.audits),23);self.assertIsNone(e.active)
        f=dict(open=100,close=110,high=112,low=99,ema30_high=105,ema30_low=95,
               rsi5=56,rsi9=56,rsi14=40,rsi21=40,rsi28=40,wma21_rsi9=51)
        self.assertEqual(reference.evaluate_entry(f,'CE')['selected_route'],'Normal Route')
        f.update(rsi14=56,rsi21=56,rsi28=56,wma21_rsi9=49)
        self.assertEqual(reference.evaluate_entry(f,'CE')['selected_route'],'WMA_bypass')
        g=dict(open=110,close=100,high=112,low=99,ema30_high=115,ema30_low=105,
               **{'rsi'+str(p):44 for p in reference.PERIODS},wma21_rsi9=51)
        self.assertEqual(reference.evaluate_entry(g,'PE')['selected_route'],'WMA_bypass')
        g['wma21_rsi9']=None
        self.assertIsNone(reference.evaluate_entry(g,'PE')['selected_route'])

    def test_midpoint_and_opposite_priority_no_same_bar_reentry(self):
        # Supplied mathematical frames isolate exact strict inequalities and event order.
        class Tracker:
            def update(self,b):return {k:v for k,v in b.items() if k not in ('start','open','high','low','close')}
        rows=minutes();e=Engine('2026-11-23');e.tracker=Tracker()
        def bar(i,side,close):
            ce=side=='CE'
            return dict(start=rows[i*3]['timestamp'],open=close-1 if ce else close+1,high=close+2,low=close-2,close=close,
                ema30_high=close-1 if ce else close+5,ema30_low=close-5 if ce else close+1,
                **{'rsi'+str(p):(60 if ce else 40) for p in reference.PERIODS},wma21_rsi9=60 if ce else 40)
        e.advance(bar(0,'CE',100),rows)
        a=e.advance(bar(1,'PE',90),rows)
        self.assertEqual([x['event'] for x in a['events']],['EXIT','ENTRY'])
        self.assertEqual(e.trades[0]['exit_reasons'],['QUALIFIED_OPPOSITE_ENTRY'])
        b=bar(2,'PE',110);b.update(ema30_low=100,rsi5=51,rsi9=51,wma21_rsi9=40)
        a=e.advance(b,rows)
        self.assertEqual(e.trades[-1]['exit_reasons'],['SIGNAL_MIDPOINT_AND_RSI5_RSI9'])
        self.assertIsNone(e.active)

    def test_cache_identity_and_corrupt_output_recovery(self):
        from hilega_rsi_two_route_v1.data import replay, ROOTS, OWN_ROOT
        from hilega_rsi_two_route_v1.calendar import UNDERLYING
        day=date(2026,10,23)
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)/ROOTS[0];root.mkdir(parents=True)
            for d in required_sessions(day)+[day]:
                (root/(str(d)+'.json')).write_text(json.dumps(dict(session_date=str(d),underlying=UNDERLYING,candles=minutes(str(d)))))
            first=replay(tmp,day);self.assertEqual(first,replay(tmp,day))
            target=root/(str(day)+'.json');body=json.loads(target.read_text());body['candles'][0]['close']+=1;target.write_text(json.dumps(body))
            changed=replay(tmp,day);self.assertNotEqual(first['cache_key'],changed['cache_key'])
            cache=Path(tmp)/OWN_ROOT/'replay'/str(day)/(changed['cache_key']+'.json')
            corrupt=json.loads(cache.read_text());corrupt['strategy_version']='WRONG';cache.write_text(json.dumps(corrupt))
            self.assertEqual(replay(tmp,day),changed)

    def test_http_contract_and_workspace(self):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        from hilega_rsi_two_route_v1.api import router
        with tempfile.TemporaryDirectory() as tmp:
            previous=os.environ.get('HILEGA_RSI_REPO_ROOT');os.environ['HILEGA_RSI_REPO_ROOT']=tmp
            try:
                app=FastAPI();app.include_router(router);client=TestClient(app)
                base='/api/live-shadow/hilega-rsi-two-route'
                self.assertEqual(client.get(base+'/rules').json()['execution_mode'],'SIMULATION_ONLY')
                self.assertEqual(client.get(base+'/live?session_date=2026-11-23').json()['status'],'NOT_PROCESSED')
                self.assertEqual(client.post(base+'/replay?session_date=2026-11-23').status_code,409)
                self.assertEqual(client.post(base+'/replay?session_date=../bad').status_code,400)
                r=client.get(base+'/sessions?start=2026-11-13&end=2026-11-18').json()['sessions']
                self.assertEqual([s['session_date'] for s in r],['2026-11-13','2026-11-16','2026-11-17','2026-11-18'])
                self.assertIn('wma21_rsi9_threshold',client.get(base+'/workspace').text)
            finally:
                if previous is None:os.environ.pop('HILEGA_RSI_REPO_ROOT')
                else:os.environ['HILEGA_RSI_REPO_ROOT']=previous

if __name__=='__main__':unittest.main()
