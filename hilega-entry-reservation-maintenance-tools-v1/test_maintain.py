from contextlib import closing,redirect_stdout
from copy import deepcopy
import io
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import Mock,patch
import maintain as m


class MaintenanceTests(unittest.TestCase):
    def setUp(self):
        tmp=tempfile.TemporaryDirectory();self.addCleanup(tmp.cleanup)
        self.root=Path(tmp.name)
        self.package=self.root/"hilega-entry-reservation-integration-tools-v1"
        self.package.mkdir()
        self.targets=dict(zip((
            "backend/market_lab/hilega_preparation_runtime_v1/atomic_binding.py",
            "backend/market_lab/hilega_preparation_runtime_v1/cash_reservation.py",
            "check-preparation-paused.py"),("runtime/atomic.py","runtime/cash.py","runtime/checker.py")))
        baseline={};hashes={}
        for name,relative in self.targets.items():
            source=self.package/relative;source.parent.mkdir(parents=True,exist_ok=True)
            source.write_text("VALUE='new'\n");hashes[relative]=m.sha(source)
            path=self.root/name;path.parent.mkdir(parents=True,exist_ok=True)
            if name.endswith("cash_reservation.py"):baseline[name]=None
            else:path.write_text("VALUE='old'\n");baseline[name]=m.sha(path)
        self.manifest=dict(runtime_targets=self.targets,baseline_sha256=baseline,
                           package_sha256=hashes)
        (self.package/"manifest.json").write_text(json.dumps(self.manifest))
        self.pin=m.sha(self.package/"manifest.json")
        p=patch.object(m,"PIN",self.pin);p.start();self.addCleanup(p.stop)
        self.proof=dict(status="PASS",pytest_exit_code=0,local_unit_tests_passed=14,
            package_manifest_sha256=self.pin,baseline_sha256=baseline,
            applied=False,services_restarted=False,database_migration_performed=False,
            production_execution_enabled=False)
        self.report=self.package/"RESERVATION_INTEGRATION_REGRESSION-fixture.json"
        self.report.write_text(json.dumps(self.proof))
        identity=self.root/m.IDENTITIES;identity.parent.mkdir(parents=True)
        identity.write_text(json.dumps(dict(children=dict(api=1,worker=2,source=3),
                                           preserved="fixture")))
        self.oldrows=[dict(role=r,pid=i+1,start_ticks=10+i) for i,r in enumerate(m.UNITS)]
        self.newrows=[dict(role=r,pid=i+101,start_ticks=100+i) for i,r in enumerate(m.UNITS)]
        self.running={r:dict(LoadState="loaded",ActiveState="active",SubState="running",
            MainPID=str(i+101)) for i,r in enumerate(m.UNITS)}
        self.stopped={r:dict(LoadState="loaded",ActiveState="inactive",SubState="dead",
                            MainPID="0") for r in m.UNITS}

    def checked(self):
        return dict(status="PAUSED_SAFE_WAITING_FOR_FRESH_SOURCE",
            process_identities_match=True,controller_mode="PAUSED",
            execution_route="PREPARATION_ONLY",journal_prefix_matches=True,
            journal_tail_remaining_records=0,production_ready=False,
            activity_counts={str(i):0 for i in range(7)})

    def test_valid_regression_proof(self):m.release(self.root)

    def test_missing_report_blocks(self):
        self.report.unlink()
        with self.assertRaisesRegex(ValueError,"VM_REGRESSION_REPORT_REQUIRED"):m.release(self.root)

    def test_failed_report_blocks(self):
        self.proof["status"]="FAIL";self.report.write_text(json.dumps(self.proof))
        with self.assertRaisesRegex(ValueError,"VM_REGRESSION_PROOF_INVALID"):m.release(self.root)

    def test_changed_source_blocks(self):
        path=self.root/next(iter(self.targets));path.write_text("CHANGED")
        with self.assertRaisesRegex(ValueError,"INSTALLED_SOURCE_CHANGED"):m.release(self.root)

    def test_unexpected_new_target_blocks(self):
        (self.root/"backend/market_lab/hilega_preparation_runtime_v1/cash_reservation.py").write_text("existing")
        with self.assertRaisesRegex(ValueError,"NEW_TARGET_ALREADY_EXISTS"):m.release(self.root)

    def test_running_inventory_must_match_units(self):
        m.validate_running(self.running,self.newrows)
        bad=deepcopy(self.newrows);bad[0]["pid"]=999
        with self.assertRaisesRegex(ValueError,"SERVICE_INVENTORY_PID_MISMATCH"):
            m.validate_running(self.running,bad)

    def test_duplicate_or_missing_role_blocks(self):
        with self.assertRaisesRegex(ValueError,"EXACTLY_THREE_MANAGED_PROCESSES_REQUIRED"):
            m.validate_running(self.running,self.newrows[:2])

    def test_stopped_requires_no_detached_process(self):
        m.validate_stopped(self.stopped,[])
        with self.assertRaisesRegex(ValueError,"STILL_RUNNING"):
            m.validate_stopped(self.stopped,self.newrows[:1])

    def test_running_unit_blocks_file_phase(self):
        with self.assertRaisesRegex(ValueError,"SERVICES_NOT_STOPPED"):
            m.validate_stopped(self.running,[])

    def test_after_hours_stale_source_can_be_safely_paused(self):
        m.check_result(self.checked())

    def test_armed_control_blocked(self):
        value=self.checked();value["controller_mode"]="ARMED"
        with self.assertRaisesRegex(ValueError,"PAUSED_STATE_OR_JOURNAL_INVALID"):
            m.check_result(value)

    def test_application_activity_blocks(self):
        value=self.checked();value["activity_counts"]["0"]=1
        with self.assertRaisesRegex(ValueError,"APPLICATION_ACTIVITY_REQUIRES_REVIEW"):
            m.check_result(value)

    def test_orphan_reservation_blocks(self):
        value=self.checked();value["local_cash_reservation_count"]=1
        with self.assertRaisesRegex(ValueError,"LOCAL_RESERVATION_REQUIRES_REVIEW"):
            m.check_result(value)

    def test_patch_backs_up_old_files_and_writes_exact_targets(self):
        backup=self.root/"backup";backup.mkdir()
        m.patch_files(self.root,self.package,self.manifest,backup)
        for name,relative in self.targets.items():
            self.assertEqual(m.sha(self.root/name),m.sha(self.package/relative))
            if self.manifest["baseline_sha256"][name]:
                self.assertEqual((backup/"files"/name).read_text(),"VALUE='old'\n")

    def test_write_failure_restores_originals_and_removes_new_file(self):
        backup=self.root/"backup";backup.mkdir()
        original=m.atomic_write
        def fail(path,raw,mode=0o600):
            if path==self.root/"check-preparation-paused.py":
                raise OSError("injected")
            return original(path,raw,mode)
        with patch.object(m,"atomic_write",side_effect=fail):
            with self.assertRaises(OSError):
                m.patch_files(self.root,self.package,self.manifest,backup)
        for name,expected in self.manifest["baseline_sha256"].items():
            if expected is None:self.assertFalse((self.root/name).exists())
            else:self.assertEqual(m.sha(self.root/name),expected)

    def test_identity_backup_is_not_overwritten_on_verification_retry(self):
        backup=self.root/"backup";backup.mkdir()
        before=(self.root/m.IDENTITIES).read_bytes()
        m.refresh_identities(self.root,self.newrows,backup)
        m.refresh_identities(self.root,self.newrows,backup)
        self.assertEqual((backup/"maintenance-identities-before.json").read_bytes(),before)
        updated=json.loads((self.root/m.IDENTITIES).read_text())
        self.assertEqual(updated["preserved"],"fixture")

    def apply_patches(self,states):
        module=Mock()
        module.processes.return_value=[]
        module.inspect.return_value=dict(active_processes=self.newrows)
        return (
            patch.object(m,"check",return_value=self.oldrows),
            patch.object(m,"inventory_module",return_value=module),
            patch.object(m,"unit_states",side_effect=states),
            patch.object(m,"activity"),
            patch.object(m,"paused_check",return_value=self.checked()),
            patch.object(m,"api_health",return_value=dict(status="ok",execution="not_enabled")))

    def test_apply_scope_and_restart_order(self):
        patches=self.apply_patches([self.stopped,self.running,self.running])
        for p in patches:p.start();self.addCleanup(p.stop)
        with patch.object(m,"call",return_value="") as call,redirect_stdout(io.StringIO()):
            m.apply(self.root)
        actions=[c.args[0] for c in call.call_args_list]
        self.assertEqual(actions[0],["systemctl","--user","stop",*m.UNITS.values()])
        self.assertEqual(actions[1:],[["systemctl","--user","start",u] for u in m.UNITS.values()])
        record=next((self.root/"backups").glob("hilega-entry-reservation-maintenance-*/transaction.json"))
        state=json.loads(record.read_text())
        self.assertEqual(state["phase"],"DEPLOYED_PAUSED_VERIFIED")
        self.assertFalse(state["production_execution_enabled"])
        self.assertFalse(state["daily_loss_limit_required"])

    def test_incomplete_stop_never_changes_code(self):
        patches=self.apply_patches([self.running])
        for p in patches:p.start();self.addCleanup(p.stop)
        with patch.object(m,"call",return_value=""),redirect_stdout(io.StringIO()):
            with self.assertRaisesRegex(ValueError,"SERVICES_NOT_STOPPED"):
                m.apply(self.root)
        for name,expected in self.manifest["baseline_sha256"].items():
            if expected is None:self.assertFalse((self.root/name).exists())
            else:self.assertEqual(m.sha(self.root/name),expected)

    def test_start_failure_is_recorded_without_automatic_retry(self):
        patches=self.apply_patches([self.stopped])
        for p in patches:p.start();self.addCleanup(p.stop)
        def command(args,**kwargs):
            if "start" in args:raise ValueError("INJECTED_START_FAILURE")
            return ""
        with patch.object(m,"call",side_effect=command) as calls,redirect_stdout(io.StringIO()):
            with self.assertRaisesRegex(ValueError,"INJECTED_START_FAILURE"):
                m.apply(self.root)
        self.assertEqual(calls.call_count,2)
        record=next((self.root/"backups").glob("hilega-entry-reservation-maintenance-*/transaction.json"))
        state=json.loads(record.read_text())
        self.assertEqual(state["phase"],"STOPPED_FOR_REVIEW_NO_AUTOMATIC_RETRY")
        self.assertEqual(state["failure_after_phase"],"STARTING")

    def activity_databases(self):
        app=self.root/"data/research/hilega-production-workspace/sim.sqlite"
        broker=self.root/"data/research/hilega-broker-adapter-closed/adapter.sqlite"
        for path in (app,broker):path.parent.mkdir(parents=True,exist_ok=True)
        with closing(sqlite3.connect(app)) as db,db:
            for t in ("intents","sim_orders","sim_fills","sim_allocation_reservations",
                      "preparation_plans","preparation_shadow_holds","preparation_outbox"):
                db.execute("CREATE TABLE "+t+"(id TEXT)")
            db.execute("CREATE TABLE control(id INTEGER,data TEXT)")
            db.execute("INSERT INTO control VALUES(1,?)",(json.dumps(dict(
                mode="PAUSED",production_execution_enabled=False)),))
            db.execute("CREATE TABLE preparation_route(id INTEGER,data TEXT)")
            db.execute("INSERT INTO preparation_route VALUES(1,?)",(json.dumps(dict(
                route="PREPARATION_ONLY",model="APPLICATION_PREPARATION_ROUTE_V1")),))
            db.execute("CREATE TABLE sim_stop_state(id INTEGER,generation INTEGER,handled INTEGER)")
            db.execute("INSERT INTO sim_stop_state VALUES(1,0,0)")
        with closing(sqlite3.connect(broker)) as db,db:
            db.execute("CREATE TABLE meta(id INTEGER,data TEXT)")
            db.execute("INSERT INTO meta VALUES(1,?)",(json.dumps(dict(mode="LIVE_CLOSED")),))
            for t in ("requests","attempts","receipts"):db.execute("CREATE TABLE "+t+"(id TEXT)")
        return app,broker

    def test_clean_databases_pass_without_writes(self):
        app,broker=self.activity_databases()
        before=[p.read_bytes() for p in (app,broker)]
        m.activity(self.root)
        self.assertEqual(before,[p.read_bytes() for p in (app,broker)])

    def test_adapter_activity_blocks_maintenance(self):
        app,broker=self.activity_databases()
        with closing(sqlite3.connect(broker)) as db,db:
            db.execute("INSERT INTO requests VALUES('fixture')")
        with self.assertRaisesRegex(ValueError,"ADAPTER_ACTIVITY_REQUIRES_REVIEW"):
            m.activity(self.root)

    def test_orphan_cash_reservation_blocks_database_preflight(self):
        app,broker=self.activity_databases()
        with closing(sqlite3.connect(app)) as db,db:
            db.execute("CREATE TABLE preparation_cash_reservations(id TEXT)")
            db.execute("INSERT INTO preparation_cash_reservations VALUES('orphan')")
        with self.assertRaisesRegex(ValueError,"LOCAL_RESERVATION_OR_BINDING_REQUIRES_REVIEW"):
            m.activity(self.root)


if __name__=="__main__":
    unittest.main()
