import uuid
import pytest
from managed_arm import unit_arg
from managed_guard import recover

def test_systemd_paths_are_quoted():assert unit_arg('/tmp/a b')=='"/tmp/a b"'
def test_systemd_specifier_rejected():
    with pytest.raises(ValueError):unit_arg('/tmp/%x')
def test_newline_rejected():
    with pytest.raises(ValueError):unit_arg('/tmp/a\nb')
def test_recovery_uses_uuid_and_verifies_pause():
    class Store:
        mode='ARMED'
        def control(self):return dict(mode=self.mode,version=4,session_date='2026-11-02')
    class Service:
        store=Store()
        def command(self,action,**kw):
            assert action=='pause';uuid.UUID(kw['request_id']);self.store.mode='PAUSED'
    recover(Service())
