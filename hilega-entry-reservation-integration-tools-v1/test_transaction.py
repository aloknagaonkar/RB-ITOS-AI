"""Unit transaction tests: actual patched binder + SQLite, synthetic upstream inputs."""
from contextlib import contextmanager,closing
from copy import deepcopy
from datetime import datetime,timezone
import importlib.util
import ast
import json
import os
from pathlib import Path
import sqlite3
import sys
import tempfile
import types
import unittest
from unittest.mock import patch,Mock
from adapter_reference import adapter as adapter_code
from signature_checks import sign

FOLDER=Path(__file__).parent
FLAGS=dict.fromkeys(("orders_sent","production_execution_enabled","entry_permission",
    "application_ledger_updated","strategy_ownership_verified",
    "real_funds_reservation_verified","reservation_release_permission",
    "allocation_reserved","source_atomic"),False)


def need(value,reason):
    if not value:raise ValueError(reason)


def load_binder(test):
    """Isolate imports; only upstream evidence/contract calls are fixture substitutes."""
    namespace="reservation_unit"
    saved=dict(sys.modules)
    pkg=types.ModuleType(namespace);pkg.__path__=[
        str(FOLDER/"runtime/market_lab/hilega_preparation_runtime_v1")]
    evidence=types.ModuleType(namespace+".evidence")
    from signature_checks import aware,day
    for key,value in dict(FLAGS=FLAGS,digest=adapter_code.sha,need=need,
                         aware=aware,day=day,readonly=None).items():
        setattr(evidence,key,value)
    limit=types.ModuleType(namespace+".limit_candidate")
    limit.build_candidate=lambda plan,hold,out,*args,**kwargs:out["disabled_request_candidate"]
    limit.fresh_plan=lambda *args,**kwargs:dict(half_cash_cap_cents=test.cap)
    account=types.ModuleType("market_lab.hilega_production_account_adapter_v1")
    account.sign=sign
    grid=types.ModuleType("market_lab.hilega_nifty_option_price_grid_v1")
    grid.PROFILE={"fixture":True}
    aliases={namespace:pkg,namespace+".evidence":evidence,
        namespace+".limit_candidate":limit,
        "market_lab.hilega_production_account_adapter_v1":account,
        "market_lab.hilega_nifty_option_price_grid_v1":grid,
        "market_lab.hilega_execution_port_v1.adapter":adapter_code}
    sys.modules.update(aliases)
    try:
        path=Path(pkg.__path__[0])/"atomic_binding.py"
        spec=importlib.util.spec_from_file_location(namespace+".atomic_binding",path)
        module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        reservation=sys.modules[namespace+".cash_reservation"]
        return module,reservation
    finally:
        for name in list(sys.modules):
            if name not in saved and (name.startswith(namespace) or name in aliases):
                del sys.modules[name]
        for name in aliases:
            if name in saved:sys.modules[name]=saved[name]


class AppStore:
    def __init__(self,path):self.path=path
    @contextmanager
    def db(self):
        db=sqlite3.connect(self.path,timeout=10)
        try:yield db;db.commit()
        except BaseException:db.rollback();raise
        finally:db.close()


class TransactionTests(unittest.TestCase):
    def setUp(self):
        tmp=tempfile.TemporaryDirectory();self.addCleanup(tmp.cleanup)
        self.root=Path(tmp.name);self.app=self.root/"app.sqlite"
        self.store=AppStore(self.app)
        self.pin=dict(scope="FIXTURE:ENTRY-RESERVATION",key="11"*32)
        self.cap=1000000
        self.now=datetime(2026,10,29,5,30,1,tzinfo=timezone.utc)
        with self.store.db() as db:
            for table in ("preparation_plans","preparation_shadow_holds","preparation_outbox"):
                db.execute("CREATE TABLE "+table+"(id TEXT PRIMARY KEY,data TEXT)")
        self.broker=adapter_code.Store(self.root/"adapter.sqlite",
                                      self.pin["scope"],"LIVE_CLOSED")
        self.mod,self.reservation=load_binder(self)
        env=patch.dict(os.environ,{"HILEGA_PREPARATION_ATOMIC_BINDING_ENABLED":"1"})
        env.start();self.addCleanup(env.stop)

    def inputs(self,key="plan"):
        body=dict(quantity=65,product="I",validity="DAY",price=100,
            tag="fixture-entry",instrument_token="NSE_FO|FIXTURE",order_type="LIMIT",
            transaction_type="BUY",disclosed_quantity=0,trigger_price=0,
            is_amo=False,slice=False)
        draft=dict(model="HILEGA_DISABLED_UPSTOX_REQUEST_DRAFT_V1",request_id=key,
            created_at=self.now.isoformat(),documented_method="POST",
            documented_host="api-hft.upstox.com",documented_path="/v3/order/place",
            body=body,fingerprint=adapter_code.sha(body),
            submission_enabled=False,entry_permission=False,orders_sent=False)
        plan=dict(FLAGS,id=key,account_scope=self.pin["scope"],quantity=65,
            instrument=body["instrument_token"],signal_at=self.now.isoformat(),direction="BULLISH")
        hold=dict(FLAGS,id=key,held_cents=660000,real_cash_reserved=False,
                  evidence_mode="REAL_CASH_OBSERVED_SHADOW_ONLY")
        out=dict(FLAGS,id=key,reservation_reference=key,disabled_request_candidate=dict(
            draft=draft,premium_cents=650000,fee_buffer_cents=10000,budget_cents=660000))
        return plan,hold,out

    def bind(self,key="plan",*,after=None):
        plan,hold,out=self.inputs(key)
        with self.mod.source_transaction(self.store,self.broker.path) as (adapter,db):
            for table,value in (("preparation_plans",plan),
                                ("preparation_shadow_holds",hold),
                                ("preparation_outbox",out)):
                db.execute("INSERT INTO "+table+" VALUES(?,?)",(key,json.dumps(value)))
            self.mod.bind_disabled_request(db,plan,hold,out,{"fixture":True},self.pin,now=self.now)
            if after:after()

    def local_rows(self):
        with self.store.db() as db:
            if not db.execute("SELECT 1 FROM sqlite_master WHERE name='preparation_cash_reservations'").fetchone():
                return []
            return [json.loads(r[0]) for r in db.execute("SELECT data FROM preparation_cash_reservations")]

    def test_reservation_and_request_commit_together(self):
        self.bind()
        row,=self.local_rows();request,=self.broker.requests()
        self.reservation.verify_row(row,self.pin)
        self.assertEqual(row["id"],request["request_id"])
        self.assertEqual(row["request_fingerprint"],adapter_code.sha({k:request[k] for k in (
            "request_id","draft","signal_id","signal_at","direction","reservation_reference")}))
        self.assertEqual(row["held_cents"],660000)
        self.assertFalse(row["broker_cash_locked"])

    def test_no_daily_limit_required(self):
        self.bind()
        row,=self.local_rows()
        self.assertIsNone(row["policy"]["daily_loss_limit_paise"])
        self.assertFalse(row["policy"]["daily_loss_limit_required"])

    def test_fault_after_local_insert_rolls_back_both(self):
        original=self.mod.reserve_local
        def fail(*args,**kwargs):
            original(*args,**kwargs);raise RuntimeError("injected")
        with patch.object(self.mod,"reserve_local",side_effect=fail):
            with self.assertRaises(RuntimeError):self.bind()
        self.assertEqual(self.local_rows(),[])
        self.assertEqual(self.broker.requests(),[])

    def test_fault_after_adapter_insert_rolls_back_both(self):
        def fail():raise RuntimeError("injected")
        with self.assertRaises(RuntimeError):self.bind(after=fail)
        self.assertEqual(self.local_rows(),[])
        self.assertEqual(self.broker.requests(),[])

    def test_exact_half_cap_fits(self):
        self.cap=660000;self.bind()
        self.assertEqual(self.local_rows()[0]["amount_cents"],self.cap)

    def test_one_paise_over_cap_refused(self):
        self.cap=659999
        with self.assertRaisesRegex(ValueError,"TOTAL_HOLDS_EXCEED_CASH_CAP"):self.bind()
        self.assertEqual(self.local_rows(),[])
        self.assertEqual(self.broker.requests(),[])

    def test_second_request_cannot_overlap(self):
        self.cap=2000000;self.bind()
        with self.assertRaises(ValueError):self.bind("second")
        self.assertEqual(len(self.local_rows()),1)
        self.assertEqual(len(self.broker.requests()),1)

    def test_closed_transport_stays_closed(self):
        self.bind()
        token=Mock(side_effect=AssertionError("No token access"))
        adapter=adapter_code.Adapter(self.broker,adapter_code.HttpTransport(token))
        self.assertEqual(adapter.submit("plan")["status"],"PRODUCTION_MUTATIONS_CLOSED_IN_CODE")
        token.assert_not_called()
        with self.broker.tx() as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM attempts").fetchone()[0],0)

    def test_wal_rejected(self):
        with closing(sqlite3.connect(self.app)) as db:db.execute("PRAGMA journal_mode=WAL")
        with self.assertRaisesRegex(ValueError,"APPLICATION_DELETE_JOURNAL_REQUIRED"):self.bind()
        self.assertEqual(self.broker.requests(),[])

    def test_disabled_atomic_mode_does_not_create_reservation(self):
        with patch.dict(os.environ,{"HILEGA_PREPARATION_ATOMIC_BINDING_ENABLED":"0"}):
            plan,hold,out=self.inputs()
            with self.store.db() as db:
                self.assertFalse(self.mod.bind_disabled_request(
                    db,plan,hold,out,{},self.pin,now=self.now))
        self.assertEqual(self.local_rows(),[])

    def test_tampered_reservation_rejected(self):
        self.bind();row=self.local_rows()[0];row["held_cents"]=0
        with self.assertRaisesRegex(ValueError,"LOCAL_CASH_RESERVATION_SIGNATURE_INVALID"):
            self.reservation.verify_row(row,self.pin)

    def test_reservation_requires_caller_transaction(self):
        plan,hold,out=self.inputs()
        with self.store.db() as db:
            with self.assertRaisesRegex(ValueError,"ACTIVE_APPLICATION_TRANSACTION_REQUIRED"):
                self.reservation.reserve_local(db,plan,hold,out,self.pin,
                    {"half_cash_cap_cents":self.cap},"fixture-fingerprint",now=self.now)


class PausedCheckerTests(unittest.TestCase):
    def test_any_reservation_row_is_visible_even_if_held_field_is_zero(self):
        source=(FOLDER/"runtime/check-preparation-paused.py").read_text()
        tree=ast.parse(source)
        fn=next(n for n in tree.body if isinstance(n,ast.FunctionDef)
                and n.name=="local_reservation_count")
        namespace={}
        exec(compile(ast.Module(body=[fn],type_ignores=[]),"checker","exec"),namespace)
        with closing(sqlite3.connect(":memory:")) as db:
            self.assertEqual(namespace["local_reservation_count"](db),0)
            db.execute("CREATE TABLE preparation_cash_reservations(id TEXT,data TEXT)")
            self.assertEqual(namespace["local_reservation_count"](db),0)
            db.execute("INSERT INTO preparation_cash_reservations VALUES('fixture','{}')")
            self.assertEqual(namespace["local_reservation_count"](db),1)

    def test_clean_paused_status_rejects_orphan_local_reservation(self):
        tree=ast.parse((FOLDER/"runtime/check-preparation-paused.py").read_text())
        expression=next(n.value for n in tree.body if isinstance(n,ast.Assign)
            and any(isinstance(t,ast.Name) and t.id=="safe" for t in n.targets))
        code=compile(ast.Expression(body=expression),"checker","eval")
        context=dict(process_match=True,control={"mode":"PAUSED"},
            route={"route":"PREPARATION_ONLY","model":"APPLICATION_PREPARATION_ROUTE_V1"},
            counts={"intents":0},prefix_matches=True,local_cash_count=1)
        self.assertFalse(eval(code,context))
        context["local_cash_count"]=0
        self.assertTrue(eval(code,context))


if __name__=="__main__":
    unittest.main()
