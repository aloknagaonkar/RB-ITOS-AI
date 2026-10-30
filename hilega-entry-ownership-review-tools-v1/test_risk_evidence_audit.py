from contextlib import closing
from copy import deepcopy
from pathlib import Path
import hashlib,json,sqlite3,tempfile,unittest
from risk_evidence_audit import audit_paths,APP_TABLES,FLAGS,AuditBlocked
from historical_receipt_checks import sha

class Fixture:
    def __init__(self,root):
        self.app=root/'app.sqlite';self.adapter=root/'adapter.sqlite';self.scope='FIXTURE:EVIDENCE'
        with closing(sqlite3.connect(self.app)) as db,db:
            for t in APP_TABLES:
                if t=='preparation_evidence':db.execute('CREATE TABLE '+t+' (digest TEXT PRIMARY KEY,data TEXT)')
                elif t=='preparation_events':db.execute('CREATE TABLE '+t+' (seq INTEGER PRIMARY KEY,data TEXT)')
                else:db.execute('CREATE TABLE '+t+' (id TEXT PRIMARY KEY,data TEXT)')
            for t in ('control','preparation_route'):db.execute('CREATE TABLE '+t+' (id INTEGER PRIMARY KEY,data TEXT)')
            db.execute('INSERT INTO control VALUES(1,?)',(json.dumps(dict(mode='PAUSED')),))
            db.execute('INSERT INTO preparation_route VALUES(1,?)',(json.dumps(dict(route='PREPARATION_ONLY',model='APPLICATION_PREPARATION_ROUTE_V1')),))
        with closing(sqlite3.connect(self.adapter)) as db,db:
            db.executescript('CREATE TABLE meta(id INTEGER PRIMARY KEY,data TEXT);CREATE TABLE requests(id TEXT PRIMARY KEY,fingerprint TEXT,data TEXT);CREATE TABLE attempts(id TEXT PRIMARY KEY,request_id TEXT,operation TEXT,data TEXT);CREATE TABLE receipts(id TEXT PRIMARY KEY,data TEXT);')
            db.execute('INSERT INTO meta VALUES(1,?)',(json.dumps(dict(scope=self.scope,mode='OFFLINE_FIXTURE')),))
    def put(self,path,table,key,value):
        with closing(sqlite3.connect(path)) as db,db:
            db.execute('INSERT OR REPLACE INTO '+table+' VALUES(?,?)',(key,json.dumps(value)))
    def get(self,path,table,key):
        with closing(sqlite3.connect(path)) as db:
            return json.loads(db.execute('SELECT data FROM '+table+' WHERE id=?',(key,)).fetchone()[0])
    def request(self):
        with closing(sqlite3.connect(self.adapter)) as db:
            return json.loads(db.execute('SELECT data FROM requests WHERE id=?',('p1',)).fetchone()[0])
    def set_request(self,value):
        stable={k:value[k] for k in ('request_id','draft','signal_id','signal_at','direction','reservation_reference')}
        with closing(sqlite3.connect(self.adapter)) as db,db:
            db.execute('INSERT OR REPLACE INTO requests VALUES(?,?,?)',(value['request_id'],sha(stable),json.dumps(value)))
    def bind(self):
        flags={k:False for k in FLAGS};key='p1';bundle={'fixture_only':True};digest=sha(bundle)
        plan=dict(flags,id=key,account_scope=self.scope,status='EVIDENCE_LINKED_UNSENT',instrument='NSE_FO|FIXTURE',quantity=65,evidence={'bundle_fingerprint':digest})
        hold=dict(flags,id=key,held_cents=10000,evidence_mode='REAL_CASH_OBSERVED_SHADOW_ONLY',real_cash_reserved=False)
        body=dict(instrument_token=plan['instrument'],product='I',transaction_type='BUY',quantity=65,order_type='LIMIT',price=1)
        draft=dict(model='HILEGA_DISABLED_UPSTOX_REQUEST_DRAFT_V1',request_id=key,documented_method='POST',documented_host='api-hft.upstox.com',documented_path='/v3/order/place',body=body,fingerprint=sha(body),submission_enabled=False,entry_permission=False,orders_sent=False)
        out=dict(flags,id=key,status='NON_EXECUTABLE_PRICING_POLICY_PENDING',request_body=None,reservation_reference=key,
                 instrument=plan['instrument'],quantity=65,bundle_fingerprint=digest,disabled_request_candidate={'draft':draft})
        request=dict(request_id=key,draft=draft,signal_id=key,signal_at='2026-10-29T11:00:00+05:30',direction='BULLISH',reservation_reference=key,state='PREPARED',order_id=None)
        self.set_request(request)
        fp=sha({k:request[k] for k in ('request_id','draft','signal_id','signal_at','direction','reservation_reference')})
        binding=dict(flags,id=key,account_scope=self.scope,model='HILEGA_ATOMIC_DISABLED_REQUEST_BINDING_V1',status='PREPARED_DISABLED_HOLD_RETAINED',
            request_fingerprint=fp,plan_fingerprint=sha(plan),hold_fingerprint=sha(hold),outbox_fingerprint=sha(out),
            held_cents=10000,cash_cap_cents=20000,bundle_fingerprint=digest,local_budget_reference_bound=True,broker_cash_locked=False)
        for t,v in (('preparation_plans',plan),('preparation_shadow_holds',hold),('preparation_outbox',out)):
            self.put(self.app,t,key,v)
        with closing(sqlite3.connect(self.app)) as db,db:
            db.execute('CREATE TABLE preparation_request_bindings(id TEXT PRIMARY KEY,data TEXT)')
            db.execute('INSERT INTO preparation_evidence VALUES(?,?)',(digest,json.dumps(bundle)))
        self.put(self.app,'preparation_request_bindings',key,binding)
    def acknowledge(self):
        request=self.request();request['order_id']='FIXTURE-ORDER';request['state']='ACKNOWLEDGED_NOT_FILLED';self.set_request(request)
        wire=dict(method='POST',host='api-hft.upstox.com',path='/v3/order/place',body=request['draft']['body'])
        attempt=dict(attempt_id='a1',request_id='p1',operation='PLACE',wire=wire)
        with closing(sqlite3.connect(self.adapter)) as db,db:
            db.execute('INSERT INTO attempts VALUES(?,?,?,?)',('a1','p1','PLACE',json.dumps(attempt)))
        receipt=dict(attempt_id='a1',wire_fingerprint=sha(wire),origin='EXPLICIT_FIXTURE_TRANSPORT',http_status=200,body=dict(status='success',data={'order_ids':['FIXTURE-ORDER']}))
        self.put(self.adapter,'receipts','a1',receipt)
    def audit(self,**kwargs):return audit_paths(self.app,self.adapter,self.scope,expected_mode='OFFLINE_FIXTURE',**kwargs)

class Tests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name);self.f=Fixture(self.root)
    def test_empty_history_is_unknown_not_zero_pnl(self):
        r=self.f.audit();self.assertIn('NO_EXECUTION_HISTORY_IS_NOT_VERIFIED_ZERO_PNL',r['gaps'])
        self.assertIsNone(r['realized_net_pnl_paise']);self.assertIsNone(r['open_net_pnl_paise'])
        self.assertFalse(r['risk_gate_input_ready']);self.assertFalse(r['entry_permission'])
    def test_empty_sources_are_unchanged(self):
        before={p:p.read_bytes() for p in (self.f.app,self.f.adapter)};names=set(self.root.iterdir())
        self.f.audit();self.assertEqual(names,set(self.root.iterdir()))
        self.assertTrue(all(p.read_bytes()==v for p,v in before.items()))
    def test_prepared_binding_is_not_ack_or_ownership(self):
        self.f.bind();r=self.f.audit()
        self.assertEqual(r['local_binding_reference_count'],1);self.assertEqual(r['historical_ack_reference_count'],0)
        self.assertEqual(r['unacknowledged_request_count'],1);self.assertFalse(r['strategy_ownership_verified'])
    def test_ack_is_not_fill_fee_or_pnl_authority(self):
        self.f.bind();self.f.acknowledge();r=self.f.audit()
        self.assertEqual(r['historical_ack_reference_count'],1)
        self.assertFalse(r['live_pnl_authenticated']);self.assertFalse(r['fees_complete']);self.assertFalse(r['production_ready'])
        self.assertFalse(r['bundle_signatures_assessed']);self.assertFalse(r['current_positions_assessed'])
    def test_populated_sources_remain_byte_identical(self):
        self.f.bind();self.f.acknowledge();before=[p.read_bytes() for p in (self.f.app,self.f.adapter)]
        self.f.audit();self.assertEqual(before,[p.read_bytes() for p in (self.f.app,self.f.adapter)])
    def test_wrong_account_scope_blocks(self):
        with self.assertRaisesRegex(AuditBlocked,'ADAPTER_PIN_SCOPE_OR_MODE_MISMATCH'):
            audit_paths(self.f.app,self.f.adapter,'OTHER',expected_mode='OFFLINE_FIXTURE')
    def test_fixture_store_cannot_pass_live_mode(self):
        with self.assertRaisesRegex(AuditBlocked,'ADAPTER_PIN_SCOPE_OR_MODE_MISMATCH'):
            audit_paths(self.f.app,self.f.adapter,self.f.scope)
    def test_armed_controller_blocks(self):
        self.f.put(self.f.app,'control',1,{'mode':'ARMED'})
        with self.assertRaisesRegex(AuditBlocked,'CONTROLLER_MUST_BE_PAUSED'):self.f.audit()
    def test_wrong_route_blocks(self):
        self.f.put(self.f.app,'preparation_route',1,{'route':'SIMULATOR'})
        with self.assertRaisesRegex(AuditBlocked,'PREPARATION_ROUTE_REQUIRED'):self.f.audit()
    def test_missing_database_is_not_created(self):
        missing=self.root/'missing.sqlite'
        with self.assertRaises(AuditBlocked):audit_paths(missing,self.f.adapter,self.f.scope)
        self.assertFalse(missing.exists())
    def test_same_database_rejected(self):
        with self.assertRaisesRegex(AuditBlocked,'DISTINCT_DATABASES_REQUIRED'):
            audit_paths(self.f.app,self.f.app,self.f.scope)
    def test_symlink_rejected(self):
        link=self.root/'link.sqlite';link.symlink_to(self.f.app)
        with self.assertRaises(AuditBlocked):audit_paths(link,self.f.adapter,self.f.scope)
    def test_wal_rejected_before_read_connection(self):
        with closing(sqlite3.connect(self.f.adapter)) as db:db.execute('PRAGMA journal_mode=WAL')
        before=set(self.root.iterdir())
        with self.assertRaisesRegex(AuditBlocked,'ROLLBACK_JOURNAL_SOURCE_REQUIRED'):self.f.audit()
        self.assertEqual(before,set(self.root.iterdir()))
    def test_missing_bound_request_blocks(self):
        self.f.bind()
        with closing(sqlite3.connect(self.f.adapter)) as db,db:db.execute('DELETE FROM requests')
        with self.assertRaisesRegex(AuditBlocked,'BOUND_REQUEST_MISSING'):self.f.audit()
    def test_changed_request_fingerprint_blocks(self):
        self.f.bind()
        with closing(sqlite3.connect(self.f.adapter)) as db,db:db.execute("UPDATE requests SET fingerprint='bad'")
        with self.assertRaisesRegex(AuditBlocked,'REQUEST_FINGERPRINT_MISMATCH'):self.f.audit()
    def test_binding_hash_change_blocks(self):
        self.f.bind();v=self.f.get(self.f.app,'preparation_request_bindings','p1');v['plan_fingerprint']='bad';self.f.put(self.f.app,'preparation_request_bindings','p1',v)
        with self.assertRaisesRegex(AuditBlocked,'APPLICATION_BINDING_HASH_MISMATCH'):self.f.audit()
    def test_permission_flag_change_blocks(self):
        self.f.bind();v=self.f.get(self.f.app,'preparation_plans','p1');v['entry_permission']=True;self.f.put(self.f.app,'preparation_plans','p1',v)
        with self.assertRaisesRegex(AuditBlocked,'APPLICATION_PERMISSION_FLAGS_CHANGED'):self.f.audit()
    def test_missing_receipt_blocks_bound_ack(self):
        self.f.bind();self.f.acknowledge()
        with closing(sqlite3.connect(self.f.adapter)) as db,db:db.execute('DELETE FROM receipts')
        with self.assertRaisesRegex(AuditBlocked,'DURABLE_PLACE_RECEIPT_REQUIRED'):self.f.audit()
    def test_wrong_receipt_origin_blocks(self):
        self.f.bind();self.f.acknowledge();r=self.f.get(self.f.adapter,'receipts','a1');r['origin']='LOCAL_HTTP_TRANSPORT';self.f.put(self.f.adapter,'receipts','a1',r)
        with self.assertRaisesRegex(AuditBlocked,'RECEIPT_PROVENANCE_MISMATCH'):self.f.audit()
    def test_wrong_ack_order_blocks(self):
        self.f.bind();self.f.acknowledge();r=self.f.get(self.f.adapter,'receipts','a1');r['body']['data']['order_ids']=['OTHER'];self.f.put(self.f.adapter,'receipts','a1',r)
        with self.assertRaisesRegex(AuditBlocked,'ACK_ORDER_BINDING_MISMATCH'):self.f.audit()
    def test_split_ack_blocks(self):
        self.f.bind();self.f.acknowledge();r=self.f.get(self.f.adapter,'receipts','a1');r['body']['data']['order_ids'].append('OTHER');self.f.put(self.f.adapter,'receipts','a1',r)
        with self.assertRaisesRegex(AuditBlocked,'ACK_ORDER_BINDING_MISMATCH'):self.f.audit()
    def test_boolean_http_status_blocks(self):
        self.f.bind();self.f.acknowledge();r=self.f.get(self.f.adapter,'receipts','a1');r['http_status']=True;self.f.put(self.f.adapter,'receipts','a1',r)
        with self.assertRaisesRegex(AuditBlocked,'SUCCESSFUL_PLACE_RECEIPT_REQUIRED'):self.f.audit()
    def test_orphan_attempt_blocks(self):
        with closing(sqlite3.connect(self.f.adapter)) as db,db:db.execute('INSERT INTO attempts VALUES(?,?,?,?)',('a1','missing','PLACE','{}'))
        with self.assertRaisesRegex(AuditBlocked,'ORPHAN_ATTEMPT_OR_RECEIPT'):self.f.audit()
    def test_orphan_receipt_blocks(self):
        self.f.put(self.f.adapter,'receipts','missing',{})
        with self.assertRaisesRegex(AuditBlocked,'ORPHAN_ATTEMPT_OR_RECEIPT'):self.f.audit()
    def test_plan_without_atomic_binding_remains_gap(self):
        self.f.bind()
        with closing(sqlite3.connect(self.f.app)) as db,db:db.execute('DELETE FROM preparation_request_bindings')
        r=self.f.audit();self.assertIn('PREPARATIONS_WITHOUT_ATOMIC_REQUEST_BINDING',r['gaps']);self.assertFalse(r['risk_gate_input_ready'])
    def test_unbound_request_fingerprint_is_still_checked(self):
        self.f.bind()
        with closing(sqlite3.connect(self.f.app)) as db,db:db.execute('DELETE FROM preparation_request_bindings')
        with closing(sqlite3.connect(self.f.adapter)) as db,db:db.execute("UPDATE requests SET fingerprint='bad'")
        with self.assertRaisesRegex(AuditBlocked,'REQUEST_FINGERPRINT_MISMATCH'):self.f.audit()
    def test_sim_history_cannot_supply_live_pnl(self):
        self.f.put(self.f.app,'sim_fills','sim-fill',{'id':'sim-fill','pnl':999})
        r=self.f.audit();self.assertIn('SIMULATOR_HISTORY_CANNOT_ESTABLISH_LIVE_PNL',r['gaps']);self.assertIsNone(r['gross_pnl_paise'])
    def test_injected_fee_flag_does_not_clear_gap(self):
        self.f.bind();self.f.acknowledge();v=self.f.request();v['fees_complete']=True;v['live_pnl']=100000;self.f.set_request(v)
        r=self.f.audit();self.assertFalse(r['fees_complete']);self.assertIsNone(r['realized_net_pnl_paise'])
    def test_persisted_evidence_hash_change_blocks(self):
        self.f.bind()
        with closing(sqlite3.connect(self.f.app)) as db,db:db.execute("UPDATE preparation_evidence SET data='{}'")
        with self.assertRaisesRegex(AuditBlocked,'PERSISTED_EVIDENCE_HASH_MISMATCH'):self.f.audit()
    def test_future_fee_or_pnl_columns_are_not_auto_adopted(self):
        with closing(sqlite3.connect(self.f.app)) as db,db:
            db.execute('CREATE TABLE fees(complete INTEGER)');db.execute('INSERT INTO fees VALUES(1)')
        r=self.f.audit();self.assertFalse(r['live_pnl_authenticated']);self.assertFalse(r['fees_complete'])
    def test_schema_error_leaks_no_raw_record(self):
        with closing(sqlite3.connect(self.f.app)) as db,db:db.execute('DROP TABLE preparation_outbox')
        with self.assertRaisesRegex(AuditBlocked,'SOURCE_SCHEMA_OR_REFERENCE_INVALID'):self.f.audit()

if __name__=='__main__':unittest.main()
