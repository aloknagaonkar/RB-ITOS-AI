"""Test harness: actual synthetic application entry followed by isolated fake execution."""
from contextlib import closing
from copy import deepcopy
from datetime import timedelta
import json
from pathlib import Path
import sqlite3
from adapter_reference.adapter import Store as FixtureStore
from adapter_reference.mapping import draft
from atomic_exit_binding import bind_fixture_exit
from exit_ack import bind_fixture_ack
from exit_fills import reconcile_fixture_exit
from exit_intent import ReferenceStore,create_reference
from gross_pnl import preview_fixture_pnl
from handoff import prepare_fixture_execution
from risk_evidence_audit import read_sources,need
from signature_checks import MODEL,LIVE,sign


class Rehearsal:
    def __init__(self,env,pin,folder):
        self.env=env;self.pin=pin;self.folder=Path(folder).resolve()
        need(pin["scope"].startswith("FIXTURE:"),"EXPLICIT_SYNTHETIC_SCOPE_REQUIRED")
        self.app=env["store"].path
        self.closed=env["adapter_store"].path
        need(self.app.resolve().parent==self.folder
             and self.closed.resolve().parent==self.folder,
             "TEMPORARY_APPLICATION_PATHS_REQUIRED")
        self.source=read_sources(self.app,self.closed,pin["scope"])
        with env["store"].db() as db:
            rows=db.execute("SELECT data FROM preparation_cash_reservations").fetchall()
        need(len(rows)==1,"DEPLOYED_APPLICATION_RESERVATION_REQUIRED")
        self.reservation=json.loads(rows[0][0])
        self.reservation_before=deepcopy(self.reservation)
        self.closed_before=self.closed.read_bytes()
        self.clock=env["clock"][0]
        self.base=self.clock-timedelta(seconds=3)
        self.store=FixtureStore(self.folder/"execution-fixture.sqlite",pin["scope"],
                                "OFFLINE_FIXTURE")
        self.adapter,self.entry_id=prepare_fixture_execution(
            self.source,self.reservation,pin,self.store,as_of=self.clock.isoformat())
        self.parent=next(r for r in self.store.requests() if r["request_id"]==self.entry_id)
        self.quantity=self.parent["draft"]["body"]["quantity"]
        self.exit_id=None
        self.reference_path=self.folder/"exit-reference-fixture.sqlite"

    def at(self,seconds):return (self.base+timedelta(seconds=seconds)).isoformat()

    def request(self,key):
        return next(r for r in self.store.requests() if r["request_id"]==key)

    def entry_fill(self):
        self.adapter.submit(self.entry_id)
        row=self.request(self.entry_id);self.entry_order=row["order_id"]
        self.adapter.transport.fill(self.entry_order,self.quantity)

    def capture(self,*,offset,include_exit=False):
        allorders=self.adapter.transport.orders()
        orders=[];trades=[];remaining=0
        for original in allorders:
            if original["side"]=="SELL" and not include_exit:continue
            row=deepcopy(original)
            row.update(pending=row["quantity"]-row["filled"]
                       if row["status"] in {"OPEN","PARTIAL"} else 0,
                       placed_at=self.at(3 if row["side"]=="BUY" else 7))
            orders.append(row)
            if row["filled"]:
                trades.append(dict(order_id=row["order_id"],
                    trade_id="fixture-buy-fill" if row["side"]=="BUY" else "fixture-sell-fill",
                    instrument=row["instrument"],product=row["product"],side=row["side"],
                    quantity=row["filled"],price="100" if row["side"]=="BUY" else "101",
                    filled_at=self.at(4 if row["side"]=="BUY" else 10)))
                remaining+=(1 if row["side"]=="BUY" else -1)*row["filled"]
        body=self.parent["draft"]["body"]
        value=dict(model=MODEL,evidence_mode=LIVE,account_scope=self.pin["scope"],
            snapshot_id="synthetic-rehearsal-"+str(offset),session_date=self.base.date().isoformat(),
            generated_at=self.at(offset),completed_at=self.at(offset+1),
            status="READ_ONLY_CAPTURED",account_identity_verified=True,
            profile_verified_before_and_after=True,account_position_rows_complete=True,
            source_atomic=False,position_fill_linkage_verified=False,live_pnl=None,
            production_execution_enabled=False,orders_sent=False,entry_permission=False,
            diagnostics={},orders=orders,trades=trades,
            positions=[dict(instrument=body["instrument_token"],product=body["product"],
                            quantity=remaining)])
        value["signature"]=sign(value,self.pin)
        return value

    def prepare_exit(self):
        source=read_sources(self.app,self.store.path,self.pin["scope"],
                            expected_mode="OFFLINE_FIXTURE")
        self.exit_reference=create_reference(source,self.capture(offset=5),self.pin,
            entry_request_id=self.entry_id,exit_key="synthetic-structural-exit",
            quantity=self.quantity,reason="SYNTHETIC_STRATEGY_EXIT",as_of=self.at(7))
        self.exit_id=self.exit_reference["id"]
        ReferenceStore.create(self.reference_path,self.pin)
        contract=deepcopy(source["plans"][self.entry_id]["evidence"]["contract"])
        exit_draft=draft(contract,request_id=self.exit_id,side="SELL",lots=1,
            as_of=self.at(7),order_type="LIMIT",limit_price="101",
            normalized_tick_rupees="0.05")
        direction=source["plans"][self.entry_id]["direction"]
        bind_fixture_exit(self.reference_path,self.store.path,self.pin,
            self.exit_reference,exit_draft,direction=direction,as_of=self.at(7))

    def submit_exit(self,*,timeout_after=False,split=False):
        self.adapter.transport.timeout_after=timeout_after
        self.adapter.transport.split_ack=split
        return self.adapter.submit(self.exit_id)

    def acknowledge_exit(self):
        return bind_fixture_ack(self.reference_path,self.store.path,self.pin,
                                self.exit_id,as_of=self.at(8))

    def fill_exit(self,quantity):
        self.adapter.transport.fill(self.request(self.exit_id)["order_id"],quantity)

    def reconcile(self,*,offset=11,snapshot=None):
        snapshot=snapshot or self.capture(offset=offset,include_exit=True)
        return reconcile_fixture_exit(self.reference_path,self.store.path,self.pin,
            snapshot,self.exit_id,as_of=self.at(offset+2))

    def gross(self,*,offset=11):
        with closing(sqlite3.connect(self.reference_path)) as db:
            state=json.loads(db.execute("SELECT data FROM exit_fill_state WHERE id=?",
                                        (self.exit_id,)).fetchone()[0])
        return preview_fixture_pnl(state,self.pin,as_of=self.at(offset+2))

    def application_retained(self):
        with self.env["store"].db() as db:
            rows=[json.loads(r[0]) for r in db.execute(
                "SELECT data FROM preparation_cash_reservations")]
        need(rows==[self.reservation_before],"APPLICATION_RESERVATION_CHANGED_BY_FIXTURE")
        need(self.closed.read_bytes()==self.closed_before,
             "CLOSED_APPLICATION_ADAPTER_CHANGED_BY_FIXTURE")
        need(self.env["store"].control()["mode"]=="PAUSED","APPLICATION_NOT_PAUSED")
        return True
