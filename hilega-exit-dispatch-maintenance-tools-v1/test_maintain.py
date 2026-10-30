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
        self.package=self.root/"hilega-exit-dispatch-closed-tools-v1"
        self.package.mkdir()
        self.targets=dict(m.TARGETS)
        baseline={};hashes={}
        for name,relative in self.targets.items():
            source=self.package/relative;source.parent.mkdir(parents=True,exist_ok=True)
            source.write_text("VALUE='new'\n");hashes[relative]=m.sha(source)
            path=self.root/name;path.parent.mkdir(parents=True,exist_ok=True)
            if name.endswith("exit_dispatch.py"):baseline[name]=None
            else:path.write_text("VALUE='old'\n");baseline[name]=m.sha(path)
        self.manifest=dict(runtime_targets=self.targets,baseline_sha256=baseline,
                           package_sha256=hashes)
        (self.package/"manifest.json").write_text(json.dumps(self.manifest))
        self.pin=m.sha(self.package/"manifest.json")
        p=patch.object(m,"PIN",self.pin);p.start();self.addCleanup(p.stop)
        self.proof=dict(status="PASS",pytest_exit_code=0,local_unit_tests_passed=10,
            package_manifest_sha256=self.pin,baseline_sha256=baseline,
            applied=False,services_restarted=False,database_migration_performed=False,
            production_execution_enabled=False,
            exit_dispatch_scope="DURABLE_REFUSED_NON_EXECUTABLE_ONLY",
            live_exit_submission_integrated=False,reservation_release_permission=False)
        self.report=self.package/"CLOSED_EXIT_DISPATCH_REGRESSION-fixture.json"
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
            journal_tail_remaining_records=0,production_ready=False,local_cash_reservation_count=0,
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
        (self.root/"backend/market_lab/hilega_preparation_runtime_v1/exit_dispatch.py").write_text("existing")
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
            if path==self.root/"backend/market_lab/hilega_preparation_runtime_v1/exit_dispatch.py":
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
        record=next((self.root/"backups").glob("hilega-exit-dispatch-maintenance-*/transaction.json"))
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
        self.assertEqual(calls.call_count,3)
        record=next((self.root/"backups").glob("hilega-exit-dispatch-maintenance-*/transaction.json"))
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


    def prepared_backup(self):
        backup=self.root/"backups/hilega-exit-dispatch-maintenance-fixture"
        backup.mkdir()
        m.patch_files(self.root,self.package,self.manifest,backup)
        m.write_json(backup/"transaction.json",dict(
            phase="DEPLOYED_PAUSED_VERIFIED",backup=str(backup),
            package_manifest_sha256=m.PIN))
        return backup

    def test_restore_returns_source_and_removes_new_module(self):
        backup=self.prepared_backup()
        m.restore_files(self.root,backup,self.manifest)
        m.release(self.root)
        for name,expected in self.manifest["baseline_sha256"].items():
            if expected is None:self.assertFalse((self.root/name).exists())
            else:self.assertEqual(m.sha(self.root/name),expected)

    def test_corrupt_backup_rejected_before_any_restore(self):
        backup=self.prepared_backup()
        name=next(n for n,v in self.manifest["baseline_sha256"].items() if v)
        (backup/"files"/name).write_text("tampered")
        before={n:(self.root/n).read_bytes() for n in self.targets}
        with self.assertRaisesRegex(ValueError,"ROLLBACK_BACKUP_CHANGED"):
            m.restore_files(self.root,backup,self.manifest)
        self.assertEqual(before,{n:(self.root/n).read_bytes() for n in self.targets})

    def test_rollback_rejects_current_code_drift(self):
        backup=self.prepared_backup()
        name=next(iter(self.targets));(self.root/name).write_text("drift")
        with patch.object(m,"call") as command:
            with self.assertRaisesRegex(ValueError,"INSTALLED_SOURCE_CHANGED"):
                m.rollback(self.root,backup)
        command.assert_not_called()

    def test_explicit_rollback_stops_restores_and_verifies_paused(self):
        backup=self.prepared_backup()
        module=Mock();module.processes.side_effect=[self.newrows,[]]
        module.inspect.return_value=dict(active_processes=self.newrows)
        with patch.object(m,"inventory_module",return_value=module), \
             patch.object(m,"unit_states",side_effect=[self.running,self.stopped,self.running]), \
             patch.object(m,"activity"), \
             patch.object(m,"verify",return_value=self.newrows) as verify, \
             patch.object(m,"call",return_value="") as command,redirect_stdout(io.StringIO()):
            m.rollback(self.root,backup)
        verify.assert_called_once_with(self.root,installed=False)
        self.assertEqual(command.call_args_list[0].args[0],
            ["systemctl","--user","stop",*m.UNITS.values()])
        self.assertEqual(len(command.call_args_list),4)
        state=json.loads((backup/"transaction.json").read_text())
        self.assertEqual(state["phase"],"ROLLED_BACK_PAUSED_VERIFIED")
        m.release(self.root)

    def test_rollback_requires_scoped_backup(self):
        backup=self.root/"backups/unrelated";backup.mkdir()
        (backup/"transaction.json").write_text("{}")
        with self.assertRaisesRegex(ValueError,"SCOPED_MAINTENANCE_BACKUP_REQUIRED"):
            m.rollback(self.root,backup)

    def test_boolean_local_reservation_count_rejected(self):
        v=self.checked();v["local_cash_reservation_count"]=False
        with self.assertRaisesRegex(ValueError,"LOCAL_RESERVATION_REQUIRES_REVIEW"):
            m.check_result(v)

    def test_exit_dispatch_permission_blocks_activity_check(self):
        app,broker=self.activity_databases()
        with closing(sqlite3.connect(app)) as db,db:
            db.execute("CREATE TABLE preparation_exit_dispatch(data TEXT)")
            db.execute("INSERT INTO preparation_exit_dispatch VALUES(?)",(
                json.dumps(dict(dispatch_status="REFUSED_CLOSED",orders_sent=True)),))
        with self.assertRaisesRegex(ValueError,"EXIT_DISPATCH_ACTIVITY_REQUIRES_REVIEW"):
            m.activity(self.root)

    def test_valid_closed_exit_record_does_not_block_read_only_check(self):
        app,broker=self.activity_databases()
        row=dict(model="HILEGA_APPLICATION_CLOSED_EXIT_DISPATCH_V1",
            dispatch_status="REFUSED_CLOSED",exit_quantity=None,parent_request_id=None)
        row.update({k:False for k in ("orders_sent","production_execution_enabled",
            "entry_permission","executable_request_created","automatic_execution_eligible",
            "reservation_release_permission")})
        with closing(sqlite3.connect(app)) as db,db:
            db.execute("CREATE TABLE preparation_exit_dispatch(data TEXT)")
            db.execute("INSERT INTO preparation_exit_dispatch VALUES(?)",(json.dumps(row),))
        before=app.read_bytes();m.activity(self.root);self.assertEqual(before,app.read_bytes())


    def test_failed_rollback_start_stops_units_and_records_failure(self):
        backup=self.prepared_backup()
        module=Mock();module.processes.side_effect=[self.newrows,[],[]]
        with patch.object(m,"inventory_module",return_value=module), \
             patch.object(m,"unit_states",side_effect=[self.running,self.stopped,self.stopped]), \
             patch.object(m,"activity"),redirect_stdout(io.StringIO()):
            def command(args,**kw):
                if "start" in args:raise ValueError("INJECTED_START_FAILURE")
                return ""
            with patch.object(m,"call",side_effect=command) as calls:
                with self.assertRaisesRegex(ValueError,"INJECTED_START_FAILURE"):
                    m.rollback(self.root,backup)
        self.assertEqual(calls.call_count,3)
        state=json.loads((backup/"transaction.json").read_text())
        self.assertEqual(state["phase"],"ROLLBACK_STOPPED_FOR_REVIEW")
        self.assertTrue(state["failure_cleanup_services_stopped"])

    def test_wrong_manifest_proof_does_not_allow_rollback(self):
        backup=self.prepared_backup()
        state=json.loads((backup/"transaction.json").read_text())
        state["package_manifest_sha256"]="wrong"
        (backup/"transaction.json").write_text(json.dumps(state))
        with patch.object(m,"call") as command:
            with self.assertRaisesRegex(ValueError,"ROLLBACK_TRANSACTION_MISMATCH"):
                m.rollback(self.root,backup)
        command.assert_not_called()


if __name__=="__main__":
    unittest.main()
