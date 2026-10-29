import importlib.util
import json
from pathlib import Path
import sqlite3
import tempfile
import types
import unittest
from unittest.mock import patch

folder = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('migration', folder / 'migrate-persistent-supervision.py')
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)

class MigrationGuards(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
    def database(self, relative, tables):
        p = self.root / relative; p.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(p) as db:
            for name in tables:
                db.execute('CREATE TABLE ' + name + ' (id INTEGER)')
        return p
    def databases(self):
        self.app = self.database('data/research/hilega-production-workspace/sim.sqlite',
            ('intents','sim_orders','sim_fills','sim_allocation_reservations',
             'preparation_plans','preparation_shadow_holds','preparation_outbox'))
        self.adapter = self.database('data/research/hilega-broker-adapter-closed/adapter.sqlite',
            ('requests','attempts','receipts'))
    def test_clean_databases_pass(self):
        self.databases(); m.clean_database(self.root)
    def test_application_activity_blocks(self):
        self.databases()
        with sqlite3.connect(self.app) as db: db.execute('INSERT INTO preparation_plans VALUES (1)')
        with self.assertRaisesRegex(RuntimeError, 'ACTIVITY_REQUIRES_REVIEW'): m.clean_database(self.root)
    def test_adapter_activity_blocks(self):
        self.databases()
        with sqlite3.connect(self.adapter) as db: db.execute('INSERT INTO attempts VALUES (1)')
        with self.assertRaisesRegex(RuntimeError, 'ACTIVITY_REQUIRES_REVIEW'): m.clean_database(self.root)
    def test_binding_activity_blocks(self):
        self.databases()
        with sqlite3.connect(self.app) as db:
            db.execute('CREATE TABLE preparation_request_bindings (id INTEGER)')
            db.execute('INSERT INTO preparation_request_bindings VALUES (1)')
        with self.assertRaisesRegex(RuntimeError, 'ACTIVITY_REQUIRES_REVIEW'): m.clean_database(self.root)
    def test_missing_database_not_created(self):
        with self.assertRaisesRegex(RuntimeError, 'DATABASE_INVALID'): m.clean_database(self.root)
        self.assertFalse((self.root / 'data').exists())
    def test_symlink_database_rejected(self):
        self.databases(); original = self.app.with_suffix('.old'); self.app.rename(original); self.app.symlink_to(original)
        with self.assertRaisesRegex(RuntimeError, 'DATABASE_INVALID'): m.clean_database(self.root)
    def test_wrong_schema_rejected(self):
        self.databases()
        with sqlite3.connect(self.adapter) as db: db.execute('DROP TABLE receipts')
        with self.assertRaisesRegex(RuntimeError, 'DATABASE_SCHEMA_INVALID'): m.clean_database(self.root)
    def test_failed_paused_checker_rejected(self):
        with patch.object(m.subprocess, 'run', return_value=types.SimpleNamespace(returncode=1, stdout='{}')):
            with self.assertRaisesRegex(RuntimeError, 'PAUSED_SAFETY_CHECK_FAILED'): m.paused_check(self.root)
    def check_result(self):
        return dict(controller_mode='PAUSED',execution_route='PREPARATION_ONLY',activity_counts={'plans':0},bridge_health={'healthy':True})
    def test_fresh_paused_check_passes(self):
        data = self.check_result()
        with patch.object(m.subprocess, 'run', return_value=types.SimpleNamespace(returncode=0, stdout=json.dumps(data))):
            self.assertEqual(m.paused_check(self.root), data)
    def test_stale_source_blocks(self):
        data = self.check_result(); data['bridge_health']['healthy']=False
        with patch.object(m.subprocess, 'run', return_value=types.SimpleNamespace(returncode=0, stdout=json.dumps(data))):
            with self.assertRaisesRegex(RuntimeError,'FRESH_SOURCE_REQUIRED'): m.paused_check(self.root)
    def test_armed_controller_blocks(self):
        data = self.check_result(); data['controller_mode']='ARMED'
        with patch.object(m.subprocess, 'run', return_value=types.SimpleNamespace(returncode=0, stdout=json.dumps(data))):
            with self.assertRaisesRegex(RuntimeError,'UNEXPECTED_CONTROL_STATE'): m.paused_check(self.root)
    def test_modified_runner_rejected_before_import(self):
        (self.root/'runner.py').write_text('raise RuntimeError("should not execute")')
        with self.assertRaisesRegex(RuntimeError,'RUNNER_CHANGED'): m.load_runner(self.root)
    def test_api_health_requires_execution_disabled(self):
        from io import BytesIO
        opener=types.SimpleNamespace(open=lambda *a,**k: BytesIO(b'{"status":"ok","execution":"enabled"}'))
        with patch.object(m,'build_opener',return_value=opener):
            with self.assertRaisesRegex(RuntimeError,'API_HEALTH_INVALID'): m.api_health()
    def test_service_manager_failure_blocks(self):
        with patch.object(m.subprocess,'run',return_value=types.SimpleNamespace(returncode=1,stdout='')):
            with self.assertRaisesRegex(RuntimeError,'SERVICE_MANAGER_COMMAND_FAILED'): m.call(['systemctl'])
    def test_unit_hash_changes_with_role(self):
        self.assertNotEqual(m.expected_unit_hash(self.root,self.root,'api'),m.expected_unit_hash(self.root,self.root,'worker'))

if __name__=='__main__': unittest.main()
